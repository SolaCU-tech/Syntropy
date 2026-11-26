import { CloudOff, FileText } from 'lucide-react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'

import { useLocalRecord } from '@/api/hooks'
import { TableIcon } from '@/components/table-icon'
import { Card, EmptyState, PageHeader } from '@/components/ui/field'
import { useToast } from '@/components/toast-context'
import { useRouteTable } from '@/features/tables/useTable'
import { useSSD, useWorkspace } from '@/features/workspace/context'
import { changedValues } from '@/lib/form-schema'
import { recordTitle, singularLabel } from '@/lib/ssd'

import { RecordForm } from './RecordForm'
import { saveRecord, type SaveOutcome } from './save'

/** Forms index: the default form for every table (custom forms come later). */
export function FormsIndex() {
  const ssd = useSSD()
  const { workspace } = useWorkspace()
  return (
    <>
      <PageHeader title="Forms" description="Quick entry for your records. They work offline too." />
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {ssd.tables.map((table) => (
          <li key={table.id}>
            <Link to={`/w/${workspace.slug}/forms/${table.key}`}>
              <Card className="flex items-center gap-3 p-4 hover:shadow-md">
                <span className="flex size-10 items-center justify-center rounded-lg bg-secondary text-primary">
                  <TableIcon name={table.icon} className="size-5" />
                </span>
                <span className="font-medium">New {singularLabel(table).toLowerCase()}</span>
              </Card>
            </Link>
          </li>
        ))}
      </ul>
    </>
  )
}

function useSaveFeedback() {
  const toast = useToast()
  const navigate = useNavigate()
  const { workspace } = useWorkspace()
  return (outcome: SaveOutcome, tableKey: string, label: string) => {
    if (outcome.kind === 'saved') {
      toast(`${label} saved.`)
      navigate(`/w/${workspace.slug}/tables/${tableKey}/${outcome.recordId}`)
    } else if (outcome.kind === 'queued') {
      toast(`${label} saved on this device. It will sync when you're back online.`)
      navigate(`/w/${workspace.slug}/tables/${tableKey}/${outcome.recordId}`)
    } else if (outcome.kind === 'conflict') {
      toast('Someone else changed this record. Choose which version to keep.')
      navigate(`/w/${workspace.slug}/sync`)
    }
  }
}

/** New record: /w/:slug/forms/:tableKey and /w/:slug/tables/:tableKey/new. */
export function NewRecordPage() {
  const ssd = useSSD()
  const table = useRouteTable()
  const { workspace, schemaVersion } = useWorkspace()
  const navigate = useNavigate()
  const feedback = useSaveFeedback()
  const [params] = useSearchParams()
  if (!table) return <EmptyState icon={<FileText />} title="We couldn't find that form" />
  const label = singularLabel(table)
  const prefill = Object.fromEntries(table.fields.filter((f) => params.has(f.id)).map((f) => [f.id, params.get(f.id)]))
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title={`New ${label.toLowerCase()}`} />
      <Card className="p-5 sm:p-6">
        <RecordForm
          key={table.id}
          ssd={ssd}
          table={table}
          prefill={prefill}
          submitLabel={`Save ${label.toLowerCase()}`}
          onCancel={() => navigate(-1)}
          onSubmit={async (values) => {
            const outcome = await saveRecord({ workspaceId: workspace.id, tableId: table.id, schemaVersion, values })
            feedback(outcome, table.key, label)
            return outcome
          }}
        />
      </Card>
    </div>
  )
}

/** Edit: /w/:slug/tables/:tableKey/:recordId/edit. Sends only the fields that changed. */
export function EditRecordPage() {
  const ssd = useSSD()
  const table = useRouteTable()
  const { recordId = '' } = useParams()
  const { workspace, schemaVersion } = useWorkspace()
  const navigate = useNavigate()
  const feedback = useSaveFeedback()
  const { record, server } = useLocalRecord(workspace.id, table?.id ?? '', recordId)

  if (!table) return <EmptyState title="We couldn't find that table" />
  if (!record) {
    if (server.isPending) return null
    return <EmptyState icon={<CloudOff />} title="We couldn't find that record" />
  }
  const label = singularLabel(table)
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title={`Edit ${recordTitle(table, record.values, record.id)}`} />
      <Card className="p-5 sm:p-6">
        <RecordForm
          key={`${record.id}-${record.version}`}
          ssd={ssd}
          table={table}
          initial={record.values}
          onCancel={() => navigate(-1)}
          onSubmit={async (values) => {
            const changes = changedValues(record.values, values)
            if (Object.keys(changes).length === 0) {
              navigate(`/w/${workspace.slug}/tables/${table.key}/${record.id}`)
              return
            }
            const outcome = await saveRecord(
              { workspaceId: workspace.id, tableId: table.id, schemaVersion, values: changes },
              // A record created on this device starts at version 1 once synced.
              { recordId: record.id, baseVersion: record.server?.version ?? 1 },
            )
            feedback(outcome, table.key, label)
            return outcome
          }}
        />
      </Card>
    </div>
  )
}
