import type { ApiRecord } from '@/api/client'
import type { Values } from '@/lib/ssd'

import type { QueuedOperation } from './db'

/** A record as this device sees it: the server's copy with any unsynced changes on top. */
export type LocalRecord = {
  id: string
  table_id: string
  version: number
  values: Values
  /** True while a change to it waits in the queue. */
  unsynced: boolean
  /** True when it was created on this device and the server hasn't confirmed it yet. */
  createdHere: boolean
  needsAttention: boolean
  server?: ApiRecord
}

export function overlay(server: ApiRecord | undefined, ops: QueuedOperation[]): LocalRecord | undefined {
  const create = ops.find((op) => op.op === 'create')
  if (!server && !create) return undefined
  let values: Values = { ...(server?.values ?? {}) }
  for (const op of ops) values = { ...values, ...op.values }
  const first = server ?? null
  return {
    id: first?.id ?? create!.record_id,
    table_id: first?.table_id ?? create!.table_id,
    version: server?.version ?? 0,
    values,
    unsynced: ops.length > 0,
    createdHere: !server && !!create,
    needsAttention: ops.some((op) => op.status !== 'pending'),
    server,
  }
}
