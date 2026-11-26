import { v7 as uuidv7, v4 as uuidv4 } from 'uuid'

import { api, isNetworkError, paths, type ApiRecord, type SyncResponse, type SyncResult } from '@/api/client'
import type { Values } from '@/lib/ssd'

import { saveToCache } from './cache'
import { db, type QueuedOperation } from './db'
import { useSyncState } from './state'

/**
 * The offline queue and sync engine (spec section 13, ADR-27).
 *
 * Every create and edit made in a form goes through the queue, online or offline, so both
 * paths behave the same. A new record gets a client-generated UUIDv7, so a sale can link to
 * a customer created offline before either has synced. Each change carries an idempotency
 * key (retries never duplicate), the base record version for edits, and the schema version
 * the form validated against.
 */

export const MAX_BATCH = 100

export function newRecordId(): string {
  return uuidv7()
}

type Enqueue = {
  workspaceId: string
  tableId: string
  schemaVersion: number
  values: Values
}

export async function enqueueCreate({ workspaceId, tableId, schemaVersion, values }: Enqueue, recordId = newRecordId()) {
  const op: QueuedOperation = {
    idempotency_key: uuidv4(),
    workspace_id: workspaceId,
    op: 'create',
    table_id: tableId,
    record_id: recordId,
    schema_version: schemaVersion,
    values,
    created_at: new Date().toISOString(),
    status: 'pending',
    attempts: 0,
  }
  op.id = await db().queue.add(op)
  return op
}

/**
 * Queue an edit. If an earlier change to the same record is still waiting and has never
 * been sent, the two are merged into one, so a record edited twice offline doesn't conflict
 * with itself.
 */
export async function enqueueUpdate(
  { workspaceId, tableId, schemaVersion, values }: Enqueue,
  recordId: string,
  baseVersion: number,
) {
  return db().transaction('rw', db().queue, async () => {
    const earlier = await db()
      .queue.where('[workspace_id+record_id]')
      .equals([workspaceId, recordId])
      .filter((op) => op.status === 'pending' && op.attempts === 0)
      .last()
    if (earlier) {
      await db().queue.update(earlier.id!, {
        values: { ...earlier.values, ...values },
        schema_version: schemaVersion,
      })
      return { ...earlier, values: { ...earlier.values, ...values } }
    }
    const op: QueuedOperation = {
      idempotency_key: uuidv4(),
      workspace_id: workspaceId,
      op: 'update',
      table_id: tableId,
      record_id: recordId,
      base_version: baseVersion,
      schema_version: schemaVersion,
      values,
      created_at: new Date().toISOString(),
      status: 'pending',
      attempts: 0,
    }
    op.id = await db().queue.add(op)
    return op
  })
}

/** The pending changes for one record, oldest first. */
export async function pendingFor(workspaceId: string, recordId: string): Promise<QueuedOperation[]> {
  return db().queue.where('[workspace_id+record_id]').equals([workspaceId, recordId]).sortBy('id')
}

/** Remove a change from the queue. Only the user (discard) or the server (applied) does this. */
export async function discard(id: number): Promise<void> {
  await db().queue.delete(id)
}

/**
 * Conflict, "keep mine": re-queue the user's values on top of the server's current version,
 * with a new idempotency key (it is a new decision).
 */
export async function keepMine(op: QueuedOperation): Promise<void> {
  if (!op.current) return
  await db().queue.update(op.id!, {
    idempotency_key: uuidv4(),
    op: 'update',
    base_version: op.current.version,
    status: 'pending',
    attempts: 0,
    error: undefined,
    current: undefined,
  })
}

/** After the user fixes a rejected change, it goes back in the queue as a new attempt. */
export async function resubmit(op: QueuedOperation, values: Values, schemaVersion: number): Promise<void> {
  await db().queue.update(op.id!, {
    idempotency_key: uuidv4(),
    values,
    schema_version: schemaVersion,
    status: 'pending',
    attempts: 0,
    error: undefined,
    current: undefined,
  })
}

/** Pending operations to send now: queue order, at most one per record (see applyResults). */
export function nextBatch(queue: QueuedOperation[]): QueuedOperation[] {
  const seen = new Set<string>()
  const blocked = new Set<string>()
  const batch: QueuedOperation[] = []
  for (const op of queue) {
    if (op.status !== 'pending') {
      blocked.add(op.record_id) // a later change waits behind one the user must resolve
      continue
    }
    if (seen.has(op.record_id) || blocked.has(op.record_id)) continue
    seen.add(op.record_id)
    batch.push(op)
    if (batch.length >= MAX_BATCH) break
  }
  return batch
}

function toRequest(op: QueuedOperation) {
  return {
    idempotency_key: op.idempotency_key,
    op: op.op,
    table_id: op.table_id,
    record_id: op.record_id,
    schema_version: op.schema_version,
    values: op.values,
    ...(op.op === 'update' ? { base_version: op.base_version } : {}),
  }
}

async function applyResult(workspaceId: string, op: QueuedOperation, result: SyncResult): Promise<void> {
  const queue = db().queue
  if (result.status === 'applied') {
    const record = result.record as ApiRecord
    await queue.delete(op.id!)
    await saveToCache(workspaceId, paths.record(workspaceId, record.table_id, record.id), record)
    // A later change to the same record was based on the version this one replaced.
    const later = await queue.where('[workspace_id+record_id]').equals([workspaceId, op.record_id]).toArray()
    for (const next of later) {
      if (next.op === 'update' && next.status === 'pending' && next.attempts === 0) {
        await queue.update(next.id!, { base_version: record.version })
      }
    }
    return
  }
  await queue.update(op.id!, {
    status: result.status,
    attempts: 0,
    error: result.error as QueuedOperation['error'],
    current: result.current,
  })
}

let running: Promise<SyncOutcome> | null = null

export type SyncOutcome = { sent: number; applied: number; offline: boolean; schemaVersion?: number }

/** Upload the queue. Concurrent calls share one run. */
export function syncNow(workspaceId: string): Promise<SyncOutcome> {
  if (!running) {
    running = runSync(workspaceId).finally(() => {
      running = null
    })
  }
  return running
}

async function runSync(workspaceId: string): Promise<SyncOutcome> {
  const state = useSyncState.getState()
  const outcome: SyncOutcome = { sent: 0, applied: 0, offline: false }
  state.setSyncing(true)
  try {
    for (let round = 0; round < 50; round++) {
      const queue = await db().queue.where('workspace_id').equals(workspaceId).sortBy('id')
      const batch = nextBatch(queue)
      if (batch.length === 0) break
      await db().queue.bulkUpdate(batch.map((op) => ({ key: op.id!, changes: { attempts: op.attempts + 1 } })))
      let response: SyncResponse
      try {
        response = await api<SyncResponse>(paths.sync(workspaceId), {
          method: 'POST',
          body: { operations: batch.map(toRequest) },
        })
      } catch (error) {
        if (isNetworkError(error)) {
          outcome.offline = true
          state.setOnline(false)
          break
        }
        throw error
      }
      state.setOnline(true)
      outcome.schemaVersion = response.schema_version
      const byKey = new Map(batch.map((op) => [op.idempotency_key, op]))
      for (const result of response.results) {
        const op = byKey.get(result.idempotency_key)
        if (!op) continue
        await applyResult(workspaceId, op, result)
        outcome.sent += 1
        if (result.status === 'applied') outcome.applied += 1
      }
    }
  } finally {
    state.setSyncing(false)
    state.setLastSync(new Date().toISOString())
  }
  return outcome
}
