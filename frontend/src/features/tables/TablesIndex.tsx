import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router'

import { useTables } from '@/api/hooks'
import { TableIcon } from '@/components/table-icon'
import { Card, PageHeader } from '@/components/ui/field'
import { useSSD, useWorkspace } from '@/features/workspace/context'
import { formatDateTime } from '@/lib/format'

export function TablesIndex() {
  const { workspace } = useWorkspace()
  const ssd = useSSD()
  const summaries = useTables(workspace.id)
  const byId = new Map((summaries.data ?? []).map((s) => [s.table_id, s]))

  return (
    <>
      <PageHeader title="Tables" description="Everything your business keeps track of." />
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {ssd.tables.map((table) => {
          const summary = byId.get(table.id)
          return (
            <li key={table.id}>
              <Link to={`/w/${workspace.slug}/tables/${table.key}`} className="group block h-full">
                <Card className="flex h-full flex-col gap-3 p-5 transition-shadow group-hover:shadow-md">
                  <div className="flex items-center gap-3">
                    <span className="flex size-10 items-center justify-center rounded-lg bg-secondary text-primary">
                      <TableIcon name={table.icon} className="size-5" />
                    </span>
                    <div className="min-w-0">
                      <p className="font-semibold text-ink">{table.label}</p>
                      <p className="text-xs text-text-secondary tabular">
                        {summary ? `${summary.record_count.toLocaleString('en-NG')} records` : '…'}
                      </p>
                    </div>
                    <ArrowRight className="ml-auto size-4 text-text-muted transition-transform group-hover:translate-x-0.5" />
                  </div>
                  {table.description && <p className="text-text-secondary">{table.description}</p>}
                  {summary?.last_updated && (
                    <p className="mt-auto text-xs text-text-muted">Updated {formatDateTime(summary.last_updated)}</p>
                  )}
                </Card>
              </Link>
            </li>
          )
        })}
      </ul>
    </>
  )
}
