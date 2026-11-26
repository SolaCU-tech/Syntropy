import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, CloudOff, Plus, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import type { ApiRecord } from '@/api/client'
import { useQueue, useRecords } from '@/api/hooks'
import { TableIcon } from '@/components/table-icon'
import { Button } from '@/components/ui/button'
import { Badge, Card, EmptyState, Input, PageHeader } from '@/components/ui/field'
import { FieldValue } from '@/features/records/values'
import { NotCachedError } from '@/features/sync/cache'
import { overlay } from '@/features/sync/local'
import { useSSD, useWorkspace } from '@/features/workspace/context'
import { isNumeric } from '@/lib/format'
import { recordTitle, singularLabel, titleField, type Values } from '@/lib/ssd'
import { cn } from '@/lib/utils'

import { FilterBuilder } from './FilterBuilder'
import { parseFilters, serializeFilters, type Filter } from './filters'
import { useRouteTable } from './useTable'

const PAGE_SIZE = 50

type Row = { id: string; values: Values; unsynced: boolean; attention: boolean }

export function TableView() {
  const table = useRouteTable()
  if (!table) return <EmptyState title="We couldn't find that table" />
  return <TableViewInner key={table.id} />
}

function TableViewInner() {
  const ssd = useSSD()
  const table = useRouteTable()!
  const { workspace } = useWorkspace()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const filters = parseFilters(params.get('filter'))
  const ordering = params.get('ordering') ?? ''
  const page = Number(params.get('page') ?? '1')
  const [search, setSearch] = useState(params.get('search') ?? '')

  // Debounce typing into the URL.
  useEffect(() => {
    const t = window.setTimeout(() => update({ search: search || null, page: null }), 300)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search])

  function update(changes: Record<string, string | null>) {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [k, v] of Object.entries(changes)) {
          if (v === null || v === '') next.delete(k)
          else next.set(k, v)
        }
        return next
      },
      { replace: true },
    )
  }

  const apiParams = new URLSearchParams()
  apiParams.set('page_size', String(PAGE_SIZE))
  if (page > 1) apiParams.set('page', String(page))
  for (const key of ['filter', 'ordering', 'search']) {
    const v = params.get(key)
    if (v) apiParams.set(key, v)
  }
  const records = useRecords(workspace.id, table.id, apiParams)
  const queue = useQueue(workspace.id)

  const rows: Row[] = useMemo(() => {
    const serverRows = records.data?.data.results ?? []
    const opsByRecord = new Map<string, typeof queue>()
    for (const op of queue) {
      if (op.table_id !== table.id) continue
      opsByRecord.set(op.record_id, [...(opsByRecord.get(op.record_id) ?? []), op])
    }
    const result: Row[] = []
    // Records created on this device show first, badged until synced (spec section 18).
    const unfiltered = filters.length === 0 && !params.get('search') && page === 1
    if (unfiltered) {
      for (const [id, ops] of opsByRecord) {
        if (serverRows.some((r) => r.id === id) || !ops.some((op) => op.op === 'create')) continue
        const local = overlay(undefined, ops)!
        result.push({ id, values: local.values, unsynced: true, attention: local.needsAttention })
      }
    }
    for (const record of serverRows as ApiRecord[]) {
      const ops = opsByRecord.get(record.id) ?? []
      const local = overlay(record, ops)!
      result.push({ id: record.id, values: local.values, unsynced: ops.length > 0, attention: local.needsAttention })
    }
    return result
  }, [records.data, queue, table.id, filters.length, params, page])

  const sorting: SortingState = ordering
    ? [{ id: ordering.replace(/^-/, ''), desc: ordering.startsWith('-') }]
    : []

  const title = titleField(table)
  // Mobile cards: the title (or date) heads the card; then the amount and the first link.
  const money = table.fields.filter((f) => f.display_role === 'money')
  const mobileDetails = [
    money.find((f) => /total/.test(f.key)) ?? money[0],
    ...table.fields.filter((f) => f.id !== title?.id && f.display_role !== 'date' && f.display_role !== 'money'),
  ]
    .filter((f) => f !== undefined)
    .slice(0, 2)
  const visible = table.fields.slice(0, 8)
  const columns = useMemo<ColumnDef<Row>[]>(
    () =>
      visible.map((field) => ({
        id: field.id,
        accessorFn: (row) => row.values[field.id],
        header: field.label,
        enableSorting: field.type !== 'reference',
        meta: { numeric: isNumeric(field) },
        cell: ({ row }) => (
          <span className="inline-flex items-center gap-2">
            <FieldValue field={field} value={row.original.values[field.id]} ssd={ssd} />
            {field.id === (title?.id ?? visible[0].id) && row.original.unsynced && (
              <Badge tone={row.original.attention ? 'warning' : 'neutral'}>
                <CloudOff /> {row.original.attention ? 'Needs attention' : 'Not synced yet'}
              </Badge>
            )}
          </span>
        ),
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [table.id, ssd],
  )

  // TanStack Table manages its own memoization; the React Compiler skips this component.
  // oxlint-disable-next-line react/incompatible-library
  const grid = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    sortDescFirst: false,
    manualPagination: true,
    manualFiltering: true,
    state: { sorting },
    onSortingChange: (updater) => {
      const next = typeof updater === 'function' ? updater(sorting) : updater
      const first = next[0]
      update({ ordering: first ? `${first.desc ? '-' : ''}${first.id}` : null, page: null })
    },
  })

  const count = records.data?.data.count ?? 0
  const pages = Math.max(1, Math.ceil(count / PAGE_SIZE))
  const base = `/w/${workspace.slug}/tables/${table.key}`
  const open = (id: string) => navigate(`${base}/${id}`)

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <TableIcon name={table.icon} className="size-6 text-primary" /> {table.label}
          </span>
        }
        description={table.description ?? undefined}
        actions={
          <Button asChild>
            <Link to={`${base}/new`}>
              <Plus /> New {singularLabel(table).toLowerCase()}
            </Link>
          </Button>
        }
      />

      <div className="mb-4 flex flex-col gap-3">
        <div className="relative max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-text-muted" />
          <Input
            type="search"
            aria-label={`Search ${table.label}`}
            placeholder={`Search ${table.label.toLowerCase()}`}
            className="pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <FilterBuilder
          ssd={ssd}
          table={table}
          filters={filters}
          onChange={(next: Filter[]) => update({ filter: serializeFilters(next), page: null })}
        />
      </div>

      {records.data?.fromCache && (
        <p className="mb-3 flex items-center gap-2 text-xs text-text-secondary">
          <CloudOff className="size-3.5" /> You're offline. Showing what was saved on this device.
        </p>
      )}

      {records.error && !rows.length ? (
        <EmptyState title={records.error instanceof NotCachedError ? 'Needs a connection' : "We couldn't load these records"}>
          {records.error instanceof NotCachedError
            ? 'This view has not been opened on this device before. You can still add records.'
            : (records.error as Error).message}
        </EmptyState>
      ) : rows.length === 0 && !records.isPending ? (
        <EmptyState icon={<TableIcon name={table.icon} />} title={filters.length || params.get('search') ? 'No matching records' : `No ${table.label.toLowerCase()} yet`}>
          {filters.length || params.get('search') ? 'Try removing a filter.' : `Add the first ${singularLabel(table).toLowerCase()}.`}
        </EmptyState>
      ) : (
        <>
          {/* Desktop and tablet: a typed grid with server-side sorting. */}
          <Card className="hidden overflow-x-auto sm:block">
            <table className="w-full text-sm">
              <thead className="border-b bg-canvas text-left text-xs text-text-secondary">
                {grid.getHeaderGroups().map((group) => (
                  <tr key={group.id}>
                    {group.headers.map((header) => {
                      const numeric = (header.column.columnDef.meta as { numeric?: boolean } | undefined)?.numeric
                      const sorted = header.column.getIsSorted()
                      return (
                        <th
                          key={header.id}
                          scope="col"
                          aria-sort={sorted ? (sorted === 'desc' ? 'descending' : 'ascending') : undefined}
                          className={cn('px-4 py-2.5 font-medium whitespace-nowrap', numeric && 'text-right')}
                        >
                          {header.column.getCanSort() ? (
                            <button
                              className={cn('inline-flex items-center gap-1 hover:text-ink', numeric && 'flex-row-reverse')}
                              onClick={header.column.getToggleSortingHandler()}
                            >
                              {flexRender(header.column.columnDef.header, header.getContext())}
                              {sorted === 'asc' ? (
                                <ArrowUp className="size-3.5" />
                              ) : sorted === 'desc' ? (
                                <ArrowDown className="size-3.5" />
                              ) : (
                                <ArrowUpDown className="size-3.5 opacity-40" />
                              )}
                            </button>
                          ) : (
                            flexRender(header.column.columnDef.header, header.getContext())
                          )}
                        </th>
                      )
                    })}
                  </tr>
                ))}
              </thead>
              <tbody>
                {grid.getRowModel().rows.map((row) => (
                  <tr
                    key={row.id}
                    className="cursor-pointer border-b last:border-0 hover:bg-canvas focus-within:bg-canvas"
                    onClick={() => open(row.original.id)}
                  >
                    {row.getVisibleCells().map((cell, i) => {
                      const numeric = (cell.column.columnDef.meta as { numeric?: boolean } | undefined)?.numeric
                      return (
                        <td key={cell.id} className={cn('px-4 py-2.5 whitespace-nowrap', numeric && 'text-right')}>
                          {i === 0 ? (
                            <Link to={`${base}/${row.original.id}`} className="outline-none focus-visible:underline" onClick={(e) => e.stopPropagation()}>
                              {flexRender(cell.column.columnDef.cell, cell.getContext())}
                            </Link>
                          ) : (
                            flexRender(cell.column.columnDef.cell, cell.getContext())
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          {/* Mobile: a card list with the title and two key values (spec section 18). */}
          <ul className="flex flex-col gap-2 sm:hidden">
            {rows.map((row) => (
              <li key={row.id}>
                <Link to={`${base}/${row.id}`}>
                  <Card className="flex flex-col gap-1 p-4">
                    <span className="flex items-center justify-between gap-2 font-medium text-ink">
                      {recordTitle(table, row.values, row.id)}
                      {row.unsynced && (
                        <Badge tone={row.attention ? 'warning' : 'neutral'}>
                          <CloudOff /> {row.attention ? 'Needs attention' : 'Not synced yet'}
                        </Badge>
                      )}
                    </span>
                    {mobileDetails.map((f) => (
                      <span key={f.id} className="flex justify-between gap-2 text-text-secondary">
                        {f.label}
                        <FieldValue field={f} value={row.values[f.id]} ssd={ssd} />
                      </span>
                    ))}
                  </Card>
                </Link>
              </li>
            ))}
          </ul>

          <div className="mt-4 flex items-center justify-between text-text-secondary">
            <span className="tabular">{count.toLocaleString('en-NG')} records</span>
            {pages > 1 && (
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })} aria-label="Previous page">
                  <ChevronLeft />
                </Button>
                <span className="tabular">
                  Page {page} of {pages}
                </span>
                <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })} aria-label="Next page">
                  <ChevronRight />
                </Button>
              </div>
            )}
          </div>
        </>
      )}
    </>
  )
}
