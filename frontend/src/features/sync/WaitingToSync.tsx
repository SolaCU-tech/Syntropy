import { CircleAlert, CloudOff, Pencil, RefreshCw, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'

import { useQueue } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { Badge, Card, EmptyState, PageHeader } from '@/components/ui/field'
import { RecordForm } from '@/features/forms/RecordForm'
import { FieldValue } from '@/features/records/values'
import { useSSD, useWorkspace } from '@/features/workspace/context'
import { formatDateTime } from '@/lib/format'
import { recordTitle, singularLabel, tableById, type SSD } from '@/lib/ssd'

import type { QueuedOperation } from './db'
import { discard, keepMine, resubmit, syncNow } from './queue'
import { useSyncState } from './state'

/** The "Waiting to sync" screen: queued changes with retry and edit (spec section 13). */
export function WaitingToSync() {
  const ssd = useSSD()
  const { workspace } = useWorkspace()
  const queue = useQueue(workspace.id)
  const { online, syncing, lastSync } = useSyncState()
  const queryClient = useQueryClient()

  async function retry() {
    await syncNow(workspace.id).catch(() => undefined)
    await queryClient.invalidateQueries({ predicate: (q) => q.queryKey[1] === workspace.id })
  }

  const attention = queue.filter((op) => op.status !== 'pending')
  const waiting = queue.filter((op) => op.status === 'pending')

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Waiting to sync"
        description={
          online
            ? 'Changes made on this device are sent as soon as they can be.'
            : "You're offline. Changes are kept safely on this device and sent when you reconnect."
        }
        actions={
          <Button variant="outline" onClick={retry} disabled={syncing}>
            <RefreshCw className={syncing ? 'animate-spin' : undefined} /> Sync now
          </Button>
        }
      />
      {lastSync && <p className="-mt-4 mb-4 text-xs text-text-muted">Last tried {formatDateTime(lastSync)}</p>}

      {queue.length === 0 ? (
        <EmptyState title="Everything is synced">Nothing is waiting on this device.</EmptyState>
      ) : (
        <div className="flex flex-col gap-6">
          {attention.length > 0 && (
            <section aria-labelledby="attention-heading" className="flex flex-col gap-3">
              <h2 id="attention-heading" className="font-semibold">
                Needs your attention ({attention.length})
              </h2>
              {attention.map((op) => (
                <AttentionCard key={op.id} ssd={ssd} op={op} onDone={retry} />
              ))}
            </section>
          )}
          {waiting.length > 0 && (
            <section aria-labelledby="waiting-heading" className="flex flex-col gap-3">
              <h2 id="waiting-heading" className="font-semibold">
                Waiting ({waiting.length})
              </h2>
              <Card>
                <ul className="divide-y">
                  {waiting.map((op) => (
                    <li key={op.id} className="flex items-center gap-3 px-5 py-3">
                      <CloudOff className="size-4 text-text-muted" aria-hidden="true" />
                      <OpSummary ssd={ssd} op={op} />
                    </li>
                  ))}
                </ul>
              </Card>
            </section>
          )}
        </div>
      )}
    </div>
  )
}

function OpSummary({ ssd, op }: { ssd: SSD; op: QueuedOperation }) {
  const { workspace } = useWorkspace()
  const table = tableById(ssd, op.table_id)
  if (!table) return <span>A change to a table that no longer exists</span>
  const verb = op.op === 'create' ? 'New' : 'Edited'
  return (
    <span className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-2">
      <Link to={`/w/${workspace.slug}/tables/${table.key}/${op.record_id}`} className="truncate hover:underline">
        {verb} {singularLabel(table).toLowerCase()}: <span className="font-medium">{recordTitle(table, op.values, op.record_id)}</span>
      </Link>
      <span className="text-xs text-text-muted">{formatDateTime(op.created_at)}</span>
    </span>
  )
}

function AttentionCard({ ssd, op, onDone }: { ssd: SSD; op: QueuedOperation; onDone: () => Promise<void> }) {
  const { schemaVersion } = useWorkspace()
  const [editing, setEditing] = useState(false)
  const table = tableById(ssd, op.table_id)

  async function remove() {
    if (window.confirm('Discard this change? It will be deleted from this device.')) await discard(op.id!)
  }

  return (
    <Card className="flex flex-col gap-4 border-warning/40 p-5">
      <div className="flex flex-wrap items-start gap-3">
        <CircleAlert className="mt-0.5 size-5 text-warning-text" aria-hidden="true" />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <OpSummary ssd={ssd} op={op} />
          <p className="text-text-secondary">{op.error?.message}</p>
          {op.error?.details && table && (
            <ul className="list-disc pl-5 text-sm text-danger">
              {Object.entries(op.error.details).map(([fieldId, messages]) => (
                <li key={fieldId}>
                  {table.fields.find((f) => f.id === fieldId)?.label ?? 'This change'}: {[messages].flat().join(' ')}
                </li>
              ))}
            </ul>
          )}
        </div>
        <Badge tone="warning">{op.status === 'conflict' ? 'Changed elsewhere' : op.status === 'schema_changed' ? 'Structure changed' : 'Not accepted'}</Badge>
      </div>

      {op.status === 'conflict' && op.current && table ? (
        <ConflictChoice ssd={ssd} op={op} onDone={onDone} />
      ) : editing && table ? (
        <RecordForm
          ssd={ssd}
          table={table}
          initial={op.op === 'create' ? op.values : { ...(op.current?.values ?? {}), ...op.values }}
          submitLabel="Save and sync"
          onCancel={() => setEditing(false)}
          onSubmit={async (values) => {
            const fixed =
              op.op === 'create' ? values : Object.fromEntries(Object.entries(values).filter(([k]) => k in op.values))
            await resubmit(op, fixed, schemaVersion)
            setEditing(false)
            await onDone()
          }}
        />
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setEditing(true)}>
            <Pencil /> Fix and resend
          </Button>
          <Button variant="ghost" onClick={remove}>
            <Trash2 /> Discard
          </Button>
        </div>
      )}
    </Card>
  )
}

/** Someone changed the record on the server: show both versions and let the user choose. */
function ConflictChoice({ ssd, op, onDone }: { ssd: SSD; op: QueuedOperation; onDone: () => Promise<void> }) {
  const table = tableById(ssd, op.table_id)!
  const changed = table.fields.filter((f) => f.id in op.values)
  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-canvas text-left text-xs text-text-secondary">
            <tr>
              <th className="px-3 py-2 font-medium">Field</th>
              <th className="px-3 py-2 font-medium">Your change</th>
              <th className="px-3 py-2 font-medium">Saved now</th>
            </tr>
          </thead>
          <tbody>
            {changed.map((f) => (
              <tr key={f.id} className="border-t">
                <td className="px-3 py-2 text-text-secondary">{f.label}</td>
                <td className="px-3 py-2 font-medium">
                  <FieldValue field={f} value={op.values[f.id]} ssd={ssd} />
                </td>
                <td className="px-3 py-2">
                  <FieldValue field={f} value={op.current!.values[f.id]} ssd={ssd} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          onClick={async () => {
            await keepMine(op)
            await onDone()
          }}
        >
          Keep my change
        </Button>
        <Button
          variant="outline"
          onClick={async () => {
            await discard(op.id!)
            await onDone()
          }}
        >
          Keep the saved version
        </Button>
      </div>
    </div>
  )
}
