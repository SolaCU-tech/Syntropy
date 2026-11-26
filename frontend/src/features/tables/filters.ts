import { cleanField } from '@/lib/form-schema'
import { formatValue } from '@/lib/format'
import type { FieldDef, Table } from '@/lib/ssd'

/**
 * One filter chip. A list of them is sent as {"all": [...]}, the same shape as the where
 * clause of the query AST (spec section 10), so saved filters carry into reports later.
 */
export type Filter = { field: string; op: string; value?: unknown }

/** Operators per field type, in owner language. Mirrors backend/apps/storage/filters.py. */
const LABELS: Record<string, string> = {
  eq: 'is',
  neq: 'is not',
  contains: 'contains',
  starts_with: 'starts with',
  gt: 'more than',
  gte: 'at least',
  lt: 'less than',
  lte: 'at most',
  in: 'is any of',
  is_empty: 'is empty',
  not_empty: 'is not empty',
}
const DATE_LABELS: Record<string, string> = { eq: 'on', gt: 'after', gte: 'on or after', lt: 'before', lte: 'on or before' }

const EMPTINESS = ['is_empty', 'not_empty']
export const OPERATORS: Record<FieldDef['type'], string[]> = {
  text: ['contains', 'eq', 'neq', 'starts_with', ...EMPTINESS],
  integer: ['eq', 'neq', 'gt', 'gte', 'lt', 'lte', ...EMPTINESS],
  decimal: ['eq', 'neq', 'gt', 'gte', 'lt', 'lte', ...EMPTINESS],
  date: ['eq', 'gte', 'lte', 'gt', 'lt', ...EMPTINESS],
  datetime: ['gte', 'lte', 'gt', 'lt', ...EMPTINESS],
  boolean: ['eq', ...EMPTINESS],
  enum: ['eq', 'neq', 'in', ...EMPTINESS],
  reference: ['eq', ...EMPTINESS],
}

export function operatorLabel(field: FieldDef, op: string): string {
  if (field.type === 'date' || field.type === 'datetime') return DATE_LABELS[op] ?? LABELS[op] ?? op
  return LABELS[op] ?? op
}

export function needsValue(op: string): boolean {
  return !EMPTINESS.includes(op)
}

/** Validate a filter value with the form rules (ranges don't apply to filters). */
export function cleanFilterValue(field: FieldDef, raw: unknown): { value: unknown } | { error: string } {
  if (field.type === 'enum' && Array.isArray(raw)) {
    return raw.length ? { value: raw } : { error: 'Pick at least one.' }
  }
  const loose = { ...field, required: true, min_value: null, max_value: null, max_length: null }
  if (field.type === 'boolean') return { value: raw === true || raw === 'true' }
  return cleanField(loose, raw)
}

export function parseFilters(raw: string | null): Filter[] {
  if (!raw) return []
  try {
    const tree = JSON.parse(raw) as { all?: Filter[] }
    return Array.isArray(tree.all) ? tree.all : []
  } catch {
    return []
  }
}

export function serializeFilters(filters: Filter[]): string | null {
  return filters.length ? JSON.stringify({ all: filters }) : null
}

/** "Total amount at least ₦1,000.00" */
export function describeFilter(table: Table, filter: Filter, titleOf?: (id: string) => string | undefined): string {
  const field = table.fields.find((f) => f.id === filter.field)
  if (!field) return 'Unknown filter'
  const op = operatorLabel(field, filter.op)
  if (!needsValue(filter.op)) return `${field.label} ${op}`
  let value: string
  if (Array.isArray(filter.value)) value = filter.value.map((v) => formatValue(field, v)).join(', ')
  else if (field.type === 'reference') value = titleOf?.(String(filter.value)) ?? 'a record'
  else value = formatValue(field, filter.value)
  return `${field.label} ${op} ${value}`
}
