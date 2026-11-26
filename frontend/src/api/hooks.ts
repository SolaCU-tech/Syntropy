import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useLiveQuery } from 'dexie-react-hooks'

import { cachedGet } from '@/features/sync/cache'
import { db, hasDB } from '@/features/sync/db'
import { overlay } from '@/features/sync/local'

import { api, paths, type ApiRecord, type LookupItem, type RecordPage, type Session, type TableSummary, type Workspace } from './client'

export const keys = {
  session: ['session'] as const,
  workspaces: ['workspaces'] as const,
  schema: (ws: string) => ['schema', ws] as const,
  tables: (ws: string) => ['tables', ws] as const,
  records: (ws: string, table: string, params?: string) => ['records', ws, table, params ?? ''] as const,
  record: (ws: string, table: string, id: string) => ['record', ws, table, id] as const,
  lookup: (ws: string, table: string) => ['lookup', ws, table] as const,
}

export function useSession() {
  return useQuery({
    queryKey: keys.session,
    queryFn: async () => {
      try {
        const session = await api<Session>(paths.session)
        localStorage.setItem('syntropy-session', JSON.stringify(session))
        return session
      } catch (error) {
        // Offline: stay signed in with the last known session (spec section 13).
        const saved = localStorage.getItem('syntropy-session')
        if (saved) return JSON.parse(saved) as Session
        throw error
      }
    },
    staleTime: 60_000,
  })
}

export function useWorkspaces(userId: number | undefined) {
  return useQuery({
    queryKey: keys.workspaces,
    enabled: userId !== undefined,
    queryFn: async () => (await cachedGet<Workspace[]>('user', paths.workspaces)).data,
  })
}

export function useTables(ws: string) {
  return useQuery({
    queryKey: keys.tables(ws),
    queryFn: async () => (await cachedGet<TableSummary[]>(ws, paths.tables(ws))).data,
  })
}

export function useRecords(ws: string, table: string, params: URLSearchParams) {
  const query = params.toString()
  return useQuery({
    queryKey: keys.records(ws, table, query),
    queryFn: ({ signal }) => cachedGet<RecordPage>(ws, `${paths.records(ws, table)}?${query}`, signal),
    placeholderData: keepPreviousData,
  })
}

export function useServerRecord(ws: string, table: string, id: string) {
  return useQuery({
    queryKey: keys.record(ws, table, id),
    queryFn: ({ signal }) => cachedGet<ApiRecord>(ws, paths.record(ws, table, id), signal),
    retry: false,
  })
}

/** Titles for link pickers: cached in full so they work offline (spec section 13). */
export function useLookup(ws: string, table: string) {
  return useQuery({
    queryKey: keys.lookup(ws, table),
    queryFn: async () => (await cachedGet<LookupItem[]>(ws, `${paths.lookup(ws, table)}?limit=5000`)).data,
    staleTime: 30_000,
  })
}

/** Unsynced changes in this workspace, live from IndexedDB. */
export function useQueue(ws: string) {
  return useLiveQuery(async () => (hasDB() ? db().queue.where('workspace_id').equals(ws).sortBy('id') : []), [ws]) ?? []
}

/** A record with this device's unsynced changes on top. */
export function useLocalRecord(ws: string, table: string, id: string) {
  const server = useServerRecord(ws, table, id)
  const ops = useQueue(ws).filter((op) => op.record_id === id)
  const record = overlay(server.data?.data, ops)
  return { record, server, ops }
}
