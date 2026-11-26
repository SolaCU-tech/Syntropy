import { api, isNetworkError } from '@/api/client'

import { db, hasDB } from './db'

/** Thrown when offline and nothing was cached for this request. */
export class NotCachedError extends Error {
  constructor() {
    super('Needs a connection')
  }
}

export type Cached<T> = { data: T; fromCache: boolean; savedAt?: string }

/**
 * GET with an offline fallback: a successful response is saved; when the device is offline
 * the last saved response is returned instead (spec section 13: recently opened tables and
 * records stay viewable offline).
 */
export async function cachedGet<T>(workspaceId: string, path: string, signal?: AbortSignal): Promise<Cached<T>> {
  const key = `${workspaceId} ${path}`
  try {
    const data = await api<T>(path, { signal })
    if (hasDB()) {
      await db().cache.put({ key, workspace_id: workspaceId, data, saved_at: new Date().toISOString() })
    }
    return { data, fromCache: false }
  } catch (error) {
    if (!isNetworkError(error) || !hasDB()) throw error
    const hit = await db().cache.get(key)
    if (!hit) throw new NotCachedError()
    return { data: hit.data as T, fromCache: true, savedAt: hit.saved_at }
  }
}

export async function saveToCache(workspaceId: string, path: string, data: unknown): Promise<void> {
  if (!hasDB()) return
  await db().cache.put({ key: `${workspaceId} ${path}`, workspace_id: workspaceId, data, saved_at: new Date().toISOString() })
}

export async function readCache<T>(workspaceId: string, path: string): Promise<T | undefined> {
  if (!hasDB()) return undefined
  return (await db().cache.get(`${workspaceId} ${path}`))?.data as T | undefined
}
