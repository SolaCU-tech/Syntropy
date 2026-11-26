import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'

import type { LookupItem, Workspace } from '@/api/client'
import { keys } from '@/api/hooks'
import { WorkspaceContext } from '@/features/workspace/context'

import { retailSSD } from './retail'

export const workspace = {
  id: 'ws-1',
  name: "Ade's Provisions",
  slug: 'ades-provisions',
  status: 'active',
  timezone: 'Africa/Lagos',
  currency: 'NGN',
  organization_name: 'Ade',
  role: 'owner',
  created_at: '2026-11-26T10:00:00Z',
} as Workspace

/** Render inside a workspace with the retail schema; lookups are pre-filled, never fetched. */
export function renderInWorkspace(ui: ReactNode, { lookups = {} as Record<string, LookupItem[]> } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  for (const table of retailSSD.tables) client.setQueryData(keys.lookup(workspace.id, table.id), lookups[table.id] ?? [])
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WorkspaceContext.Provider value={{ workspace, ssd: retailSSD, schemaVersion: 1, offline: false }}>{ui}</WorkspaceContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
