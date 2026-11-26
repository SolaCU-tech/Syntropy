import { Filter as FilterIcon, Plus, X } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input, Select } from '@/components/ui/field'
import { relationshipFor, type FieldDef, type SSD, type Table } from '@/lib/ssd'
import { useTitles } from '@/features/records/useTitles'

import { cleanFilterValue, describeFilter, needsValue, OPERATORS, operatorLabel, type Filter } from './filters'

/** Filter chips plus an "Add filter" editor (spec section 18, table toolbar). */
export function FilterBuilder({
  ssd,
  table,
  filters,
  onChange,
}: {
  ssd: SSD
  table: Table
  filters: Filter[]
  onChange: (filters: Filter[]) => void
}) {
  const [adding, setAdding] = useState(false)
  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="Filters">
      {filters.map((filter, i) => (
        <FilterChip key={i} ssd={ssd} table={table} filter={filter} onRemove={() => onChange(filters.filter((_, j) => j !== i))} />
      ))}
      {adding ? (
        <FilterEditor
          ssd={ssd}
          table={table}
          onCancel={() => setAdding(false)}
          onAdd={(filter) => {
            onChange([...filters, filter])
            setAdding(false)
          }}
        />
      ) : (
        <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
          <FilterIcon /> Add filter
        </Button>
      )}
      {filters.length > 1 && (
        <Button variant="ghost" size="sm" onClick={() => onChange([])}>
          Clear all
        </Button>
      )}
    </div>
  )
}

function FilterChip({ ssd, table, filter, onRemove }: { ssd: SSD; table: Table; filter: Filter; onRemove: () => void }) {
  const field = table.fields.find((f) => f.id === filter.field)
  const rel = field?.type === 'reference' ? relationshipFor(ssd, field.id) : undefined
  const titles = useTitles(rel?.to_table)
  const text = describeFilter(table, filter, (id) => titles.get(id))
  return (
    <span className="inline-flex h-8 items-center gap-1 rounded-full border bg-secondary pr-1 pl-3 text-xs font-medium text-primary">
      {text}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove filter: ${text}`}
        className="flex size-6 items-center justify-center rounded-full hover:bg-primary/10"
      >
        <X className="size-3.5" />
      </button>
    </span>
  )
}

function FilterEditor({
  ssd,
  table,
  onAdd,
  onCancel,
}: {
  ssd: SSD
  table: Table
  onAdd: (filter: Filter) => void
  onCancel: () => void
}) {
  const [fieldId, setFieldId] = useState(table.fields[0].id)
  const field = table.fields.find((f) => f.id === fieldId)!
  const [op, setOp] = useState(OPERATORS[field.type][0])
  const [raw, setRaw] = useState<unknown>('')
  const [error, setError] = useState<string | null>(null)

  function changeField(id: string) {
    const next = table.fields.find((f) => f.id === id)!
    setFieldId(id)
    setOp(OPERATORS[next.type][0])
    setRaw(next.type === 'boolean' ? true : '')
    setError(null)
  }

  function add() {
    if (!needsValue(op)) return onAdd({ field: fieldId, op })
    const result = cleanFilterValue(field, raw)
    if ('error' in result) return setError(result.error)
    onAdd({ field: fieldId, op, value: result.value })
  }

  return (
    <div
      className="flex w-full flex-wrap items-start gap-2 rounded-lg border bg-surface p-2 sm:w-auto"
      role="group"
      aria-label="New filter"
      onKeyDown={(e) => {
        if (e.key === 'Escape') onCancel()
      }}
    >
      <Select aria-label="Field" className="sm:w-40" value={fieldId} onChange={(e) => changeField(e.target.value)}>
        {table.fields.map((f) => (
          <option key={f.id} value={f.id}>
            {f.label}
          </option>
        ))}
      </Select>
      <Select aria-label="Condition" className="sm:w-36" value={op} onChange={(e) => setOp(e.target.value)}>
        {OPERATORS[field.type].map((o) => (
          <option key={o} value={o}>
            {operatorLabel(field, o)}
          </option>
        ))}
      </Select>
      {needsValue(op) && (
        <div className="flex flex-col gap-1">
          <FilterValueInput ssd={ssd} field={field} op={op} value={raw} onChange={setRaw} invalid={!!error} />
          {error && <span className="text-xs text-danger">{error}</span>}
        </div>
      )}
      <Button size="sm" className="h-11 sm:h-9" onClick={add}>
        <Plus /> Add
      </Button>
      <Button size="sm" variant="ghost" className="h-11 sm:h-9" onClick={onCancel}>
        Cancel
      </Button>
    </div>
  )
}

function FilterValueInput({
  ssd,
  field,
  op,
  value,
  onChange,
  invalid,
}: {
  ssd: SSD
  field: FieldDef
  op: string
  value: unknown
  onChange: (value: unknown) => void
  invalid: boolean
}) {
  const rel = field.type === 'reference' ? relationshipFor(ssd, field.id) : undefined
  const titles = useTitles(rel?.to_table)
  const common = { 'aria-label': 'Value', 'aria-invalid': invalid || undefined, className: 'sm:w-44' }

  if (field.type === 'enum' && op === 'in') {
    const selected = Array.isArray(value) ? (value as string[]) : []
    return (
      <Select
        {...common}
        multiple
        className="h-24 sm:w-44"
        value={selected}
        onChange={(e) => onChange(Array.from(e.target.selectedOptions, (o) => o.value))}
      >
        {field.options?.map((o) => (
          <option key={o.key} value={o.key}>
            {o.label}
          </option>
        ))}
      </Select>
    )
  }
  if (field.type === 'enum' || field.type === 'boolean' || field.type === 'reference') {
    const options =
      field.type === 'enum'
        ? (field.options ?? []).map((o) => [o.key, o.label])
        : field.type === 'boolean'
          ? [
              ['true', 'Yes'],
              ['false', 'No'],
            ]
          : [...titles.entries()].sort((a, b) => a[1].localeCompare(b[1]))
    return (
      <Select {...common} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose…</option>
        {options.map(([key, label]) => (
          <option key={key} value={key}>
            {label}
          </option>
        ))}
      </Select>
    )
  }
  const type = field.type === 'date' ? 'date' : field.type === 'datetime' ? 'datetime-local' : 'text'
  const numeric = field.type === 'integer' || field.type === 'decimal'
  return (
    <Input
      {...common}
      type={type}
      inputMode={numeric ? 'decimal' : undefined}
      value={String(value ?? '')}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.preventDefault()
      }}
    />
  )
}
