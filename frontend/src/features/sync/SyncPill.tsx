import { CircleAlert, CloudOff, Loader2, Wifi } from 'lucide-react'
import { Link } from 'react-router'

import { useQueue } from '@/api/hooks'
import { cn } from '@/lib/utils'

import { useSyncState } from './state'

/** Online, Offline (3 waiting), Syncing, or Needs attention (spec section 13, UX). */
export function SyncPill({ workspaceId, slug }: { workspaceId: string; slug: string }) {
  const { online, syncing } = useSyncState()
  const queue = useQueue(workspaceId)
  const attention = queue.filter((op) => op.status !== 'pending').length
  const waiting = queue.length - attention

  let label: string
  let icon: React.ReactNode
  let tone: string
  if (attention > 0) {
    label = 'Needs attention'
    icon = <CircleAlert />
    tone = 'bg-warning/15 text-warning-text'
  } else if (syncing) {
    label = 'Syncing'
    icon = <Loader2 className="animate-spin" />
    tone = 'bg-secondary text-primary'
  } else if (!online) {
    label = waiting ? `Offline (${waiting} waiting)` : 'Offline'
    icon = <CloudOff />
    tone = 'bg-canvas text-text-secondary border'
  } else {
    label = waiting ? `${waiting} waiting` : 'Online'
    icon = <Wifi />
    tone = 'bg-success/10 text-success-text'
  }

  return (
    <Link
      to={`/w/${slug}/sync`}
      role="status"
      aria-live="polite"
      data-testid="sync-pill"
      className={cn(
        'inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-medium whitespace-nowrap [&_svg]:size-3.5',
        tone,
      )}
    >
      {icon}
      {label}
    </Link>
  )
}
