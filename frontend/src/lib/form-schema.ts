import { z } from 'zod'

import type { FieldDef, Table, Values } from './ssd'

/**
 * The generated form schema for one SSD table (spec section 10, form engine).
 *
 * It mirrors the backend's validation (backend/apps/storage/values.py) so a form validates
 * the same way offline as the server will when the change syncs: same required rules, same
 * ranges, same decimal places, and the same canonical values. Decimals stay strings from the
 * input to the API and are compared as scaled integers, never JS floats (ADR-25).
 *
 * Form inputs hold strings (booleans hold booleans). The schema's output is the API's
 * values object, keyed by field ID.
 */

export const MAX_SAFE_INTEGER = Number.MAX_SAFE_INTEGER
const INT_RE = /^-?\d{1,16}$/
const DECIMAL_RE = /^-?\d{1,28}(\.\d{1,10})?$/
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const DEFAULT_MAX_TEXT = 10_000
export const REQUIRED = 'This field is required.'

export type FormValues = Record<string, unknown>

/** Compare two decimal strings exactly. Returns -1, 0 or 1. */
export function compareDecimal(a: string, b: string): number {
  const scale = Math.max(places(a), places(b))
  const x = scaled(a, scale)
  const y = scaled(b, scale)
  return x < y ? -1 : x > y ? 1 : 0
}

function places(value: string): number {
  const dot = value.indexOf('.')
  return dot === -1 ? 0 : value.length - dot - 1
}

function scaled(value: string, scale: number): bigint {
  const negative = value.startsWith('-')
  const [whole, frac = ''] = value.replace('-', '').split('.')
  const digits = BigInt(whole + frac.padEnd(scale, '0'))
  return negative ? -digits : digits
}

function digitsCount(value: string): number {
  const significant = value.replace('-', '').replace('.', '').replace(/^0+/, '')
  return significant.length || 1
}

function rangeError(field: FieldDef, value: string): string | null {
  if (field.min_value != null && compareDecimal(value, field.min_value) < 0) return `Must be at least ${field.min_value}.`
  if (field.max_value != null && compareDecimal(value, field.max_value) > 0) return `Must be at most ${field.max_value}.`
  return null
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Validate one raw input value; returns the canonical API value or an error message. */
export function cleanField(field: FieldDef, raw: unknown): { value: unknown } | { error: string } {
  const blank = raw === undefined || raw === null || (typeof raw === 'string' && raw.trim() === '')
  if (blank) {
    if (field.type === 'boolean' && raw === undefined) return { value: null }
    return field.required ? { error: REQUIRED } : { value: null }
  }
  switch (field.type) {
    case 'text': {
      const text = String(raw)
      const limit = field.max_length ?? DEFAULT_MAX_TEXT
      if (text.length > limit) return { error: `Must be at most ${limit} characters.` }
      return { value: text }
    }
    case 'integer': {
      const text = String(raw).trim().replace(/,/g, '')
      if (!INT_RE.test(text)) return { error: 'Must be a whole number.' }
      const n = Number(text)
      if (Math.abs(n) > MAX_SAFE_INTEGER) return { error: 'Is too large.' }
      const range = rangeError(field, text)
      return range ? { error: range } : { value: n }
    }
    case 'decimal': {
      const text = String(raw).trim().replace(/,/g, '')
      if (!DECIMAL_RE.test(text)) return { error: 'Must be a number such as 1500.00.' }
      const scale = field.scale ?? 0
      if (places(text) > scale) return { error: `Can have at most ${scale} decimal places.` }
      const [whole, frac = ''] = text.replace('-', '').split('.')
      const normalWhole = whole.replace(/^0+(?=\d)/, '')
      const isZero = /^0*$/.test(normalWhole + frac)
      const canonical = `${text.startsWith('-') && !isZero ? '-' : ''}${normalWhole}${scale ? '.' + frac.padEnd(scale, '0') : ''}`
      const precision = field.precision ?? 28
      if (digitsCount(canonical) > precision) return { error: `Has more than ${precision} digits.` }
      const range = rangeError(field, canonical)
      return range ? { error: range } : { value: canonical }
    }
    case 'boolean':
      return typeof raw === 'boolean' ? { value: raw } : { error: 'Must be true or false.' }
    case 'date': {
      const text = String(raw)
      if (!DATE_RE.test(text)) return { error: 'Must be a date such as 2026-11-24.' }
      const [y, m, d] = text.split('-').map(Number)
      const date = new Date(Date.UTC(y, m - 1, d))
      if (date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d) {
        return { error: 'Must be a real date.' }
      }
      return { value: text }
    }
    case 'datetime': {
      // <input type="datetime-local"> has no zone; the device's zone applies.
      const date = new Date(String(raw))
      if (Number.isNaN(date.getTime())) return { error: 'Must be a date and time.' }
      return { value: date.toISOString().replace('.000Z', 'Z') }
    }
    case 'enum': {
      const keys = (field.options ?? []).map((o) => o.key)
      return keys.includes(String(raw)) ? { value: String(raw) } : { error: `Must be one of: ${keys.join(', ')}.` }
    }
    case 'reference':
      return UUID_RE.test(String(raw)) ? { value: String(raw).toLowerCase() } : { error: 'Pick a linked record.' }
  }
  return { error: 'Unsupported field.' }
}

/** Build the Zod schema for a table's form. */
export function formSchema(table: Table) {
  return z.record(z.string(), z.unknown()).transform((input, ctx) => {
    const output: Values = {}
    for (const field of table.fields) {
      const result = cleanField(field, input[field.id])
      if ('error' in result) {
        ctx.addIssue({ code: 'custom', message: result.error, path: [field.id] })
      } else {
        output[field.id] = result.value
      }
    }
    return output
  })
}

/** Turn an API record's values into form input values. */
export function toFormValues(table: Table, values: Values | undefined, defaults = true): FormValues {
  const form: FormValues = {}
  for (const field of table.fields) {
    const value = values ? values[field.id] : defaults ? field.default : undefined
    if (field.type === 'boolean') {
      form[field.id] = value === true
    } else if (field.type === 'datetime' && typeof value === 'string') {
      const date = new Date(value)
      const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
      form[field.id] = local.toISOString().slice(0, 16)
    } else {
      form[field.id] = value === null || value === undefined ? '' : String(value)
    }
  }
  return form
}

/** The values that differ from the original record: an edit sends only these. */
export function changedValues(original: Values, next: Values): Values {
  const changed: Values = {}
  for (const [key, value] of Object.entries(next)) {
    const before = original[key] ?? null
    if (before !== (value ?? null)) changed[key] = value
  }
  return changed
}
