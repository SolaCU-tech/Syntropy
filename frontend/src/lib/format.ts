import type { FieldDef } from './ssd'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export const WORKSPACE_TIMEZONE = 'Africa/Lagos'

const moneyFormats = new Map<string, Intl.NumberFormat>()

/**
 * Money arrives as a decimal string and is formatted from the string, never through a JS
 * float (ADR-25). Intl.NumberFormat formats numeric strings exactly.
 */
export function formatMoney(value: string, currency = 'NGN'): string {
  let format = moneyFormats.get(currency)
  if (!format) {
    format = new Intl.NumberFormat('en-NG', { style: 'currency', currency })
    moneyFormats.set(currency, format)
  }
  return format.format(value as unknown as number)
}

export function formatDecimal(value: string, scale: number | null): string {
  return new Intl.NumberFormat('en-NG', {
    minimumFractionDigits: scale ?? 0,
    maximumFractionDigits: scale ?? 0,
  }).format(value as unknown as number)
}

/** "2026-11-24" -> "24 Nov 2026", without any timezone shift. */
export function formatDate(value: string): string {
  const [y, m, d] = value.split('-').map(Number)
  if (!y || !m || !d) return value
  return `${d} ${MONTHS[m - 1]} ${y}`
}

/** An ISO datetime shown day-first in the workspace timezone. */
export function formatDateTime(value: string, timeZone = WORKSPACE_TIMEZONE): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone,
  }).format(date)
}

export function todayISO(timeZone = WORKSPACE_TIMEZONE): string {
  // en-CA formats as YYYY-MM-DD.
  return new Intl.DateTimeFormat('en-CA', { timeZone }).format(new Date())
}

/** Plain text for a field value; links are resolved by the caller. */
export function formatValue(field: FieldDef, value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  switch (field.type) {
    case 'decimal':
      return field.currency ? formatMoney(String(value), field.currency) : formatDecimal(String(value), field.scale)
    case 'integer':
      return new Intl.NumberFormat('en-NG').format(Number(value))
    case 'date':
      return formatDate(String(value))
    case 'datetime':
      return formatDateTime(String(value))
    case 'boolean':
      return value ? 'Yes' : 'No'
    case 'enum':
      return field.options?.find((o) => o.key === value)?.label ?? String(value)
    default:
      return String(value)
  }
}

export function isNumeric(field: FieldDef): boolean {
  return field.type === 'integer' || field.type === 'decimal'
}
