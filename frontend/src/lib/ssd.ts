import type { components } from '@/api/types'

import { formatDate } from './format'

export type SSD = components['schemas']['SSD']
export type Table = components['schemas']['Table']
export type FieldDef = components['schemas']['FieldDef']
export type Relationship = components['schemas']['Relationship']
export type Values = Record<string, unknown>

export function tableByKey(ssd: SSD, key: string): Table | undefined {
  return ssd.tables.find((t) => t.key === key)
}

export function tableById(ssd: SSD, id: string): Table | undefined {
  return ssd.tables.find((t) => t.id === id)
}

export function titleField(table: Table): FieldDef | undefined {
  return table.fields.find((f) => f.display_role === 'title')
}

/** The relationship a reference field belongs to. */
export function relationshipFor(ssd: SSD, fieldId: string): Relationship | undefined {
  return ssd.relationships?.find((r) => r.from_field === fieldId)
}

/** Relationships whose links point at records of this table ("sales for this customer"). */
export function incomingRelationships(ssd: SSD, tableId: string): Relationship[] {
  return (ssd.relationships ?? []).filter((r) => r.to_table === tableId)
}

/** A record's name in lists and link pickers: its title field, else a short fallback. */
export function recordTitle(table: Table, values: Values, id?: string): string {
  const title = titleField(table)
  const value = title ? values[title.id] : undefined
  if (typeof value === 'string' && value.trim()) return value
  const singular = singularLabel(table)
  // No title field (a sale, a payment): name it by its date when it has one.
  const dateField = table.fields.find((f) => f.display_role === 'date' && f.type === 'date')
  const date = dateField ? values[dateField.id] : undefined
  if (typeof date === 'string' && date) return `${singular} on ${formatDate(date)}`
  return id ? `${singular} ${id.slice(-6)}` : singular
}

/** "Sales" -> "sale", for phrases such as "New sale" and "3 sales". */
export function singularLabel(table: Table): string {
  return table.label.replace(/ies$/, 'y').replace(/s$/, '')
}
