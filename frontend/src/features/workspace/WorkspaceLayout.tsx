import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useEffect, useMemo } from 'react'
import { Navigate, useParams } from 'react-router'

import { ApiError, paths } from '@/api/client'
import { keys, useLookup, useWorkspaces } from '@/api/hooks'
import { EmptyState } from '@/components/ui/field'
import { useAuth } from '@/features/auth/auth-context'
import { AppShell } from '@/features/shell/AppShell'
import { cachedGet, NotCachedError } from '@/features/sync/cache'
import { syncNow } from '@/features/sync/queue'
import { useSyncState } from '@/features/sync/state'
import type { SSD } from '@/lib/ssd'

import { WorkspaceContext, type WorkspaceValue } from './context'

const SYNC_EVERY_MS = 30_000

export function FullPageSpinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex min-h-dvh items-center justify-center gap-2 text-text-secondary">
      <Loader2 className="size-4 animate-spin" aria-hidden="true" /> {label}
    </div>
  )
}

export function WorkspaceLayout() {
  const { slug } = useParams()
  const { user } = useAuth()
  const workspaces = useWorkspaces(user?.id)
  const workspace = workspaces.data?.find((w) => w.slug === slug)

  const schema = useQuery({
    queryKey: keys.schema(workspace?.id ?? ''),
    enabled: !!workspace,
    queryFn: async () => {
      try {
        const result = await cachedGet<SSD>(workspace!.id, paths.schema(workspace!.id))
        return { ssd: result.data, offline: result.fromCache }
      } catch (error) {
        if (error instanceof ApiError && error.code === 'no_active_schema') return { ssd: null, offline: false }
        throw error
      }
    },
    staleTime: 60_000,
  })

  const value = useMemo<WorkspaceValue | null>(() => {
    if (!workspace || !schema.data) return null
    return {
      workspace,
      ssd: schema.data.ssd,
      schemaVersion: schema.data.ssd?.version ?? 0,
      offline: schema.data.offline,
    }
  }, [workspace, schema.data])

  if (workspaces.isPending || (workspace && schema.isPending)) return <FullPageSpinner />
  if (!workspace) {
    if (workspaces.data && workspaces.data.length > 0) return <Navigate to={`/w/${workspaces.data[0].slug}/home`} replace />
    return (
      <div className="p-8">
        <EmptyState title="We couldn't find that workspace">Check the link, or ask the owner to add you.</EmptyState>
      </div>
    )
  }
  if (!value) {
    const offline = schema.error instanceof NotCachedError
    return (
      <div className="p-8">
        <EmptyState title={offline ? 'Needs a connection' : "We couldn't load this workspace"}>
          {offline ? 'Open this workspace once while online so it works offline next time.' : 'Try again in a moment.'}
        </EmptyState>
      </div>
    )
  }
  return (
    <WorkspaceContext.Provider value={value}>
      <SyncDriver workspaceId={workspace.id} />
      {value.ssd?.tables.map((t) => <LookupWarmer key={t.id} workspaceId={workspace.id} tableId={t.id} />)}
      <AppShell />
    </WorkspaceContext.Provider>
  )
}

/** Keeps each table's link-picker list cached for offline entry (spec section 13, step 1). */
function LookupWarmer({ workspaceId, tableId }: { workspaceId: string; tableId: string }) {
  useLookup(workspaceId, tableId)
  return null
}

/** Uploads the queue on reconnect, periodically, and when the app opens. */
function SyncDriver({ workspaceId }: { workspaceId: string }) {
  const queryClient = useQueryClient()
  const setOnline = useSyncState((s) => s.setOnline)

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      if (cancelled) return
      const outcome = await syncNow(workspaceId).catch(() => null)
      if (outcome && outcome.sent > 0) {
        await queryClient.invalidateQueries({ predicate: (q) => q.queryKey[1] === workspaceId })
      }
      if (outcome && outcome.schemaVersion !== undefined) {
        const current = queryClient.getQueryData<{ ssd: SSD | null }>(keys.schema(workspaceId))
        if (current?.ssd && current.ssd.version !== outcome.schemaVersion) {
          await queryClient.invalidateQueries({ queryKey: keys.schema(workspaceId) })
        }
      }
    }
    const goOnline = () => {
      setOnline(true)
      void run()
    }
    const goOffline = () => setOnline(false)
    setOnline(navigator.onLine)
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    const timer = window.setInterval(run, SYNC_EVERY_MS)
    void run()
    return () => {
      cancelled = true
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
      window.clearInterval(timer)
    }
  }, [workspaceId, queryClient, setOnline])
  return null
}
