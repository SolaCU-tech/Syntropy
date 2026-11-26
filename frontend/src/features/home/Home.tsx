import { CircleAlert, CloudOff, Plus } from 'lucide-react'
import { Link } from 'react-router'

import { useQueue, useTables } from '@/api/hooks'
import { TableIcon } from '@/components/table-icon'
import { Card, EmptyState } from '@/components/ui/field'
import { useAuth } from '@/features/auth/auth-context'
import { useWorkspace } from '@/features/workspace/context'
import { formatDate, todayISO } from '@/lib/format'
import { singularLabel } from '@/lib/ssd'

/** Home: greeting, quick actions and what needs attention. KPIs and insights arrive in Phase 5. */
export function Home() {
  const { workspace, ssd } = useWorkspace()
  const { user } = useAuth()
  const queue = useQueue(workspace.id)
  const tables = useTables(workspace.id)
  const attention = queue.filter((op) => op.status !== 'pending').length
  const waiting = queue.length - attention
  const base = `/w/${workspace.slug}`

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="text-text-secondary">{formatDate(todayISO())}</p>
        <h1 className="text-2xl font-semibold tracking-tight">
          Hello{user?.first_name ? `, ${user.first_name}` : ''}. Here's {workspace.name}.
        </h1>
      </div>

      {!ssd ? (
        <EmptyState title="Your workspace has no structure yet">
          Uploading your records and describing your business sets it up. That arrives in the next phase.
        </EmptyState>
      ) : (
        <>
          <section aria-labelledby="quick-heading">
            <h2 id="quick-heading" className="mb-3 font-semibold">
              Quick actions
            </h2>
            <div className="flex flex-wrap gap-2">
              {ssd.tables.map((t) => (
                <Link
                  key={t.id}
                  to={`${base}/forms/${t.key}`}
                  className="inline-flex h-11 items-center gap-2 rounded-md border bg-surface px-4 font-medium shadow-sm hover:bg-secondary"
                >
                  <Plus className="size-4 text-primary" /> New {singularLabel(t).toLowerCase()}
                </Link>
              ))}
            </div>
          </section>

          {queue.length > 0 && (
            <section aria-labelledby="attention-heading">
              <h2 id="attention-heading" className="mb-3 font-semibold">
                Needs your attention
              </h2>
              <Link to={`${base}/sync`}>
                <Card className="flex items-center gap-3 p-4 hover:shadow-md">
                  {attention ? <CircleAlert className="size-5 text-warning-text" /> : <CloudOff className="size-5 text-text-secondary" />}
                  <span>
                    {attention > 0 && `${attention} change${attention === 1 ? '' : 's'} need${attention === 1 ? 's' : ''} a decision. `}
                    {waiting > 0 && `${waiting} change${waiting === 1 ? ' is' : 's are'} waiting to sync.`}
                  </span>
                </Card>
              </Link>
            </section>
          )}

          <section aria-labelledby="tables-heading">
            <h2 id="tables-heading" className="mb-3 font-semibold">
              Your tables
            </h2>
            <div className="grid gap-3 sm:grid-cols-3">
              {ssd.tables.map((t) => {
                const count = tables.data?.find((s) => s.table_id === t.id)?.record_count
                return (
                  <Link key={t.id} to={`${base}/tables/${t.key}`}>
                    <Card className="flex items-center gap-3 p-4 hover:shadow-md">
                      <TableIcon name={t.icon} className="size-5 text-primary" />
                      <span className="font-medium">{t.label}</span>
                      <span className="ml-auto text-text-secondary tabular">{count?.toLocaleString('en-NG') ?? ''}</span>
                    </Card>
                  </Link>
                )
              })}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
