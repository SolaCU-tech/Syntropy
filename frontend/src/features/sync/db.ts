import Dexie, { type EntityTable } from 'dexie'

import type { ApiRecord, ErrorDetails } from '@/api/client'
import type { Values } from '@/lib/ssd'

/**
 * The device's offline store (spec section 13), one IndexedDB database per signed-in user so
 * caches never mix between people sharing a phone. Logging out deletes it.
 *
 *   cache  API responses the app has read (schema, lookups, recently opened tables and
 *          records), keyed by workspace and URL, so they can be shown offline.
 *   queue  Changes made on this device that the server hasn't confirmed yet. Nothing leaves
 *          the queue until the server says it was applied, or the user discards it.
 */

export type QueueStatus = 'pending' | 'conflict' | 'rejected' | 'schema_changed'

export interface QueuedOperation {
  id?: number
  idempotency_key: string
  workspace_id: string
  op: 'create' | 'update'
  table_id: string
  record_id: string
  base_version?: number
  schema_version: number
  values: Values
  created_at: string
  status: QueueStatus
  /** Upload attempts whose outcome is unknown (the response never arrived). */
  attempts: number
  error?: { code: string; message: string; details?: ErrorDetails }
  /** For a conflict: the record as it is on the server now. */
  current?: ApiRecord
}

export interface CachedResponse {
  key: string
  workspace_id: string
  data: unknown
  saved_at: string
}

export class SyntropyDB extends Dexie {
  queue!: EntityTable<QueuedOperation, 'id'>
  cache!: EntityTable<CachedResponse, 'key'>

  constructor(name: string) {
    super(name)
    this.version(1).stores({
      queue: '++id, workspace_id, [workspace_id+record_id], [workspace_id+table_id], status',
      cache: 'key, workspace_id',
    })
  }
}

const PREFIX = 'syntropy-user-'
let current: SyntropyDB | null = null

/** Open the signed-in user's database. */
export function openUserDB(userId: number | string): SyntropyDB {
  const name = `${PREFIX}${userId}`
  if (current?.name !== name) {
    current?.close()
    current = new SyntropyDB(name)
  }
  return current
}

export function db(): SyntropyDB {
  if (!current) throw new Error('No user database is open.')
  return current
}

export function hasDB(): boolean {
  return current !== null
}

/** Delete the signed-in user's cache and queue (logout). */
export async function deleteUserDB(): Promise<void> {
  if (!current) return
  const database = current
  current = null
  database.close()
  await Dexie.delete(database.name)
}
