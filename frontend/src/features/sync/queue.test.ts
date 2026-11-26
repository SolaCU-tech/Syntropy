import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CUSTOMERS, SALES } from '@/test/retail'

import { db, deleteUserDB, openUserDB, type QueuedOperation } from './db'
import { overlay } from './local'
import { enqueueCreate, enqueueUpdate, keepMine, nextBatch, syncNow } from './queue'
import { useSyncState } from './state'

const WS = 'ws-1'
const base = { workspaceId: WS, schemaVersion: 1 }

type SentOp = { idempotency_key: string; op: string; record_id: string; base_version?: number; values: Record<string, unknown> }

function record(op: SentOp, version = 1) {
  return {
    id: op.record_id,
    table_id: CUSTOMERS,
    version,
    schema_version: 1,
    values: op.values,
    created_by: 1,
    created_at: '2026-11-26T10:00:00Z',
    updated_at: '2026-11-26T10:00:00Z',
  }
}

/** A fake server: decides each operation's outcome with `decide`. */
function server(decide: (op: SentOp) => Record<string, unknown> = (op) => ({ status: 'applied', record: record(op) })) {
  const batches: SentOp[][] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body)) as { operations: SentOp[] }
      batches.push(body.operations)
      const results = body.operations.map((op) => ({ idempotency_key: op.idempotency_key, replayed: false, ...decide(op) }))
      return new Response(JSON.stringify({ schema_version: 1, results }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return batches
}

beforeEach(() => {
  openUserDB('test')
})

afterEach(async () => {
  vi.unstubAllGlobals()
  await deleteUserDB()
})

describe('offline queue', () => {
  it('keeps changes made offline and sends them in order when back online', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const customer = await enqueueCreate({ ...base, tableId: CUSTOMERS, values: { fld_customer_name: 'Ada' } })
    await enqueueCreate({ ...base, tableId: SALES, values: { fld_sale_customer: customer.record_id } })

    const offline = await syncNow(WS)
    expect(offline.offline).toBe(true)
    expect(useSyncState.getState().online).toBe(false)
    expect(await db().queue.count()).toBe(2) // nothing is lost

    const batches = server()
    const outcome = await syncNow(WS)
    expect(outcome).toMatchObject({ sent: 2, applied: 2, offline: false })
    expect(batches[0].map((op) => op.op)).toEqual(['create', 'create'])
    expect(batches[0][1].values.fld_sale_customer).toBe(customer.record_id)
    expect(await db().queue.count()).toBe(0)
  })

  it('reuses the same idempotency key when retrying after a lost response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const op = await enqueueCreate({ ...base, tableId: CUSTOMERS, values: { fld_customer_name: 'Ada' } })
    await syncNow(WS)
    const batches = server()
    await syncNow(WS)
    expect(batches[0][0].idempotency_key).toBe(op.idempotency_key)
  })

  it('uses UUIDv7 IDs for records created on the device', async () => {
    const op = await enqueueCreate({ ...base, tableId: CUSTOMERS, values: {} })
    expect(op.record_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  })

  it('merges a second edit into an unsent first one, so it never conflicts with itself', async () => {
    await enqueueUpdate({ ...base, tableId: CUSTOMERS, values: { fld_customer_area: 'Yaba' } }, 'rec-1', 3)
    await enqueueUpdate({ ...base, tableId: CUSTOMERS, values: { fld_customer_phone: '0803' } }, 'rec-1', 3)
    const queue = await db().queue.toArray()
    expect(queue).toHaveLength(1)
    expect(queue[0].values).toEqual({ fld_customer_area: 'Yaba', fld_customer_phone: '0803' })
    expect(queue[0].base_version).toBe(3)
  })

  it('merges an edit into a record created offline that has not been sent', async () => {
    const created = await enqueueCreate({ ...base, tableId: CUSTOMERS, values: { fld_customer_name: 'Ada' } })
    await enqueueUpdate({ ...base, tableId: CUSTOMERS, values: { fld_customer_name: 'Adaeze' } }, created.record_id, 1)
    const queue = await db().queue.toArray()
    expect(queue).toHaveLength(1)
    expect(queue[0]).toMatchObject({ op: 'create', values: { fld_customer_name: 'Adaeze' } })
  })

  it('sends one change per record per batch and rebases the next on the new version', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await enqueueUpdate({ ...base, tableId: CUSTOMERS, values: { fld_customer_area: 'Yaba' } }, 'rec-1', 3)
    await syncNow(WS) // attempted: later edits can no longer merge into it
    await enqueueUpdate({ ...base, tableId: CUSTOMERS, values: { fld_customer_area: 'Ikeja' } }, 'rec-1', 3)

    let version = 3
    const batches = server((op) => {
      expect(op.base_version).toBe(version)
      version += 1
      return { status: 'applied', record: record(op, version) }
    })
    await syncNow(WS)
    expect(batches.map((b) => b.length)).toEqual([1, 1])
    expect(batches[1][0].base_version).toBe(4)
  })

  it('keeps conflicts and rejections for the user, never dropping them', async () => {
    const current = { ...record({ idempotency_key: '', op: 'update', record_id: 'rec-1', values: { fld_customer_area: 'Lekki' } }), version: 5 }
    await enqueueUpdate({ ...base, tableId: CUSTOMERS, values: { fld_customer_area: 'Yaba' } }, 'rec-1', 4)
    await enqueueCreate({ ...base, tableId: CUSTOMERS, values: { fld_customer_phone: '0803' } })
    server((op) =>
      op.op === 'update'
        ? { status: 'conflict', current, error: { code: 'version_conflict', message: 'Changed elsewhere' } }
        : { status: 'rejected', error: { code: 'duplicate_value', message: 'Taken', details: { fld_customer_phone: ['Taken'] } } },
    )
    await syncNow(WS)
    const [conflict, rejected] = await db().queue.orderBy('id').toArray()
    expect(conflict).toMatchObject({ status: 'conflict', current: { version: 5 } })
    expect(rejected).toMatchObject({ status: 'rejected', error: { code: 'duplicate_value' } })

    // "Keep my change": re-queued on the server's version with a new key.
    await keepMine(conflict)
    const requeued = (await db().queue.get(conflict.id!))!
    expect(requeued).toMatchObject({ status: 'pending', base_version: 5 })
    expect(requeued.idempotency_key).not.toBe(conflict.idempotency_key)
  })

  it('holds later changes to a record behind one that needs attention', () => {
    const op = (id: number, record_id: string, status: QueuedOperation['status']) =>
      ({ id, record_id, status }) as QueuedOperation
    const batch = nextBatch([op(1, 'a', 'conflict'), op(2, 'a', 'pending'), op(3, 'b', 'pending')])
    expect(batch.map((o) => o.id)).toEqual([3])
  })
})

describe('overlay', () => {
  it('shows unsynced changes on top of the server copy', () => {
    const server = record({ idempotency_key: '', op: 'update', record_id: 'r', values: { fld_customer_name: 'Ada', fld_customer_area: 'Yaba' } })
    const ops = [{ op: 'update', status: 'pending', values: { fld_customer_area: "Ikeja" } }] as unknown as QueuedOperation[]
    expect(overlay(server, ops)).toMatchObject({
      values: { fld_customer_name: 'Ada', fld_customer_area: 'Ikeja' },
      unsynced: true,
      createdHere: false,
    })
    expect(overlay(server, [])?.unsynced).toBe(false)
    expect(overlay(undefined, [])).toBeUndefined()
  })
})
