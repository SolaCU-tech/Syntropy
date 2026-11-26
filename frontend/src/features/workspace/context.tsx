import { createContext, useContext } from 'react'

import type { Workspace } from '@/api/client'
import type { SSD } from '@/lib/ssd'

export type WorkspaceValue = {
  workspace: Workspace
  /** The active schema, or null when the workspace has no published structure yet. */
  ssd: SSD | null
  schemaVersion: number
  /** True when the schema came from the offline cache. */
  offline: boolean
}

export const WorkspaceContext = createContext<WorkspaceValue | null>(null)

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext)
  if (!value) throw new Error('useWorkspace outside a workspace')
  return value
}

/** The active schema; screens under a workspace with a structure can rely on it. */
export function useSSD(): SSD {
  const { ssd } = useWorkspace()
  if (!ssd) throw new Error('No active schema')
  return ssd
}
