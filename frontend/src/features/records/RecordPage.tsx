import { ArrowLeft, CircleAlert, CloudOff, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { api, ApiError, isNetworkError, paths } from '@/api/client'
import { useLocalRecord, useRecords } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { Badge, Card, EmptyState } from '@/components/ui/field'
import { useToast } from '@/components/toast-context'
import { NotCachedError } from '@/features/sync/cache'
import { useSyncState } from '@/features/sync/state'
import { useRouteTable } from '@/features/tables/useTable'
import { useSSD, useWorkspace } from '@/features/workspace/context'
import { formatDateTime } from '@/lib/format'
import { recordTitle, singularLabel, tableById, titleField, type Relationship, type SSD, type Table } from '@/lib/ssd'
import { useQueryClient } from '@tanstack/react-query'

import { FieldValue } from './values'

export function RecordPage() {
  const ssd = useSSD()
  const table = useRouteTable()
  const { recordId = '' } = useParams()
  const { workspace } = useWorkspace()
  const { record, server, ops } = useLocalRecord(workspace.id, table?.id ?? '', recordId)

  if (!table) return <EmptyState title="We couldn't find that table" />
  const base = `/w/${workspace.slug}/tables/${table.key}`
  if (!record) {
    if (server.isPending) return null
    const offline = server.error instanceof NotCachedError
    return (
      <EmptyState icon={<CloudOff />} title={offline ? 'Needs a connection' : "We couldn't find that record"}>
        {offline ? 'This record has not been opened on this device before.' : <Link to={base}>Back to {table.label}</Link>}
      </EmptyState>
    )
  }

  const title = titleField(table)
  const canEdit = workspace.role !== 'viewer'
  const fields = table.fields.filter((f) => f.id !== title?.id)

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Link to={base} className="mb-3 inline-flex items-center gap-1 text-sm text-text-secondary hover:text-ink">
          <ArrowLeft className="size-4" /> {table.label}
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">{recordTitle(table, record.values, record.id)}</h1>
            <div className="flex flex-wrap gap-2">
              {record.needsAttention ? (
                <Badge tone="warning">
                  <CircleAlert /> Needs attention
                </Badge>
              ) : record.unsynced ? (
                <Badge>
                  <CloudOff /> Not synced yet
                </Badge>
              ) : null}
              {server.data?.fromCache && (
                <Badge>
                  <CloudOff /> Offline copy
                </Badge>
              )}
            </div>
          </div>
          {canEdit && (
            <div className="flex gap-2">
              <Button asChild variant="outline">
                <Link to={`${base}/${record.id}/edit`}>
                  <Pencil /> Edit
                </Link>
              </Button>
              {record.server && <DeleteButton table={table} recordId={record.id} version={record.server.version} />}
            </div>
          )}
        </div>
      </div>

      {record.needsAttention && (
        <Card className="flex flex-wrap items-center justify-between gap-3 border-warning/40 bg-warning/5 p-4">
          <p>{ops.find((o) => o.status !== 'pending')?.error?.message}</p>
          <Button asChild size="sm" variant="outline">
            <Link to={`/w/${workspace.slug}/sync`}>Review</Link>
          </Button>
        </Card>
      )}

      <Card>
        <dl className="divide-y">
          {fields.map((field) => (
            <div key={field.id} className="grid grid-cols-1 gap-1 px-5 py-3 sm:grid-cols-3">
              <dt className="text-text-secondary">{field.label}</dt>
              <dd className="sm:col-span-2">
                <FieldValue field={field} value={record.values[field.id]} ssd={ssd} />
              </dd>
            </div>
          ))}
        </dl>
        {record.server && (
          <p className="border-t px-5 py-3 text-xs text-text-muted">
            Added {formatDateTime(record.server.created_at)} · Last changed {formatDateTime(record.server.updated_at)}
          </p>
        )}
      </Card>

      {!record.createdHere &&
        ssdIncoming(ssd, table).map((rel) => (
          <LinkedRecords key={rel.id} ssd={ssd} rel={rel} recordId={record.id} parentTitle={recordTitle(table, record.values)} canAdd={canEdit} />
        ))}
    </div>
  )
}

function ssdIncoming(ssd: SSD, table: Table): Relationship[] {
  return (ssd.relationships ?? []).filter((r) => r.to_table === table.id)
}

/** "12 sales" for this customer, the latest few, and "New sale for Adaeze". */
function LinkedRecords({
  ssd,
  rel,
  recordId,
  parentTitle,
  canAdd,
}: {
  ssd: SSD
  rel: Relationship
  recordId: string
  parentTitle: string
  canAdd: boolean
}) {
  const { workspace } = useWorkspace()
  const source = tableById(ssd, rel.from_table)!
  const filter = JSON.stringify({ all: [{ field: rel.from_field, op: 'eq', value: recordId }] })
  const params = new URLSearchParams({ filter, page_size: '5' })
  const records = useRecords(workspace.id, source.id, params)
  const count = records.data?.data.count
  const label = singularLabel(source).toLowerCase()
  const base = `/w/${workspace.slug}/tables/${source.key}`
  // The fields that say most about a linked record: its name, when, how much, and status.
  const others = source.fields.filter((f) => f.id !== rel.from_field)
  const pick = (role: string) => others.find((f) => f.display_role === role)
  const money = others.filter((f) => f.display_role === 'money')
  const amount = money.find((f) => /total/.test(f.key)) ?? money[0]
  const shown = [pick('title'), pick('date'), amount, pick('status')].filter((f) => f !== undefined)
  if (shown.length < 2) shown.push(...others.filter((f) => !shown.includes(f)).slice(0, 3 - shown.length))

  return (
    <Card data-testid={`linked-${source.key}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-5 py-3">
        <h2 className="font-semibold">
          {source.label}
          {count !== undefined && <span className="ml-2 font-normal text-text-secondary tabular">{count.toLocaleString('en-NG')}</span>}
        </h2>
        <div className="flex gap-2">
          {count !== undefined && count > 5 && (
            <Button asChild variant="ghost" size="sm">
              <Link to={`${base}?filter=${encodeURIComponent(filter)}`}>See all</Link>
            </Button>
          )}
          {canAdd && (
            <Button asChild variant="outline" size="sm">
              <Link to={`${base}/new?${rel.from_field}=${recordId}`}>
                <Plus /> New {label} for {parentTitle}
              </Link>
            </Button>
          )}
        </div>
      </div>
      {records.data?.data.results.length ? (
        <ul className="divide-y">
          {records.data.data.results.map((r) => (
            <li key={r.id}>
              <Link to={`${base}/${r.id}`} className="flex flex-wrap items-center gap-x-6 gap-y-1 px-5 py-3 hover:bg-canvas">
                {shown.map((f) => (
                  <span key={f.id} className="min-w-24">
                    <FieldValue field={f} value={r.values[f.id]} ssd={ssd} />
                  </span>
                ))}
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-5 py-4 text-text-secondary">{records.isPending ? 'Loading…' : `No ${source.label.toLowerCase()} yet.`}</p>
      )}
    </Card>
  )
}

/** Deleting needs a connection (Agreed 26 Nov 2026) and is restricted when records link here. */
function DeleteButton({ table, recordId, version }: { table: Table; recordId: string; version: number }) {
  const { workspace } = useWorkspace()
  const online = useSyncState((s) => s.online)
  const navigate = useNavigate()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [problem, setProblem] = useState<string | null>(null)

  async function remove() {
    if (!window.confirm(`Delete this ${singularLabel(table).toLowerCase()}? This can't be undone.`)) return
    try {
      await api(`${paths.record(workspace.id, table.id, recordId)}?version=${version}`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ predicate: (q) => q.queryKey[1] === workspace.id })
      toast('Deleted.')
      navigate(`/w/${workspace.slug}/tables/${table.key}`)
    } catch (error) {
      if (isNetworkError(error)) setProblem('Deleting needs a connection.')
      else if (error instanceof ApiError && error.code === 'record_in_use')
        setProblem(`You can't delete this: other records link to it. ${Object.values(error.details).flat().join(' ')}`)
      else if (error instanceof ApiError) setProblem(error.message)
    }
  }

  return (
    <>
      <Button variant="outline" onClick={remove} disabled={!online} title={online ? undefined : 'Needs a connection'}>
        <Trash2 /> Delete
      </Button>
      {problem && (
        <p role="alert" className="basis-full text-sm text-danger">
          {problem}
        </p>
      )}
    </>
  )
}
