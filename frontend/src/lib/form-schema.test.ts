import { describe, expect, it } from 'vitest'

import { CUSTOMERS, PRODUCTS, SALES, table } from '@/test/retail'

import { changedValues, cleanField, compareDecimal, formSchema, REQUIRED, toFormValues } from './form-schema'
import type { FieldDef } from './ssd'

const field = (tableId: string, id: string) => table(tableId).fields.find((f) => f.id === id)! as FieldDef

describe('compareDecimal', () => {
  it('compares exactly, without floats', () => {
    expect(compareDecimal('0.3', '0.30')).toBe(0)
    expect(compareDecimal('9000.00', '90000')).toBe(-1)
    expect(compareDecimal('-1.5', '-1.25')).toBe(-1)
    expect(compareDecimal('12345678901234567890.01', '12345678901234567890.001')).toBe(1)
  })
})

describe('cleanField mirrors the backend values module', () => {
  const price = field(PRODUCTS, 'fld_product_unit_price') // decimal, scale 2, min 0, NGN

  it.each([
    ['1500', '1500.00'],
    ['1,500.5', '1500.50'],
    ['007.10', '7.10'],
    ['0', '0.00'],
  ])('canonicalizes decimal %s as %s', (raw, canonical) => {
    expect(cleanField(price, raw)).toEqual({ value: canonical })
  })

  it.each([
    ['1.234', 'at most 2 decimal places'],
    ['-1', 'at least 0'],
    ['abc', 'Must be a number'],
    ['1e3', 'Must be a number'],
  ])('refuses decimal %s', (raw, message) => {
    const result = cleanField(price, raw)
    expect('error' in result && result.error).toContain(message)
  })

  it('requires required fields', () => {
    expect(cleanField(price, '  ')).toEqual({ error: REQUIRED })
    expect(cleanField(field(CUSTOMERS, 'fld_customer_area'), '')).toEqual({ value: null })
  })

  it('checks integers, dates, enums and references', () => {
    const qty = field(SALES, 'fld_sale_quantity')
    expect(cleanField(qty, '3')).toEqual({ value: 3 })
    expect('error' in cleanField(qty, '2.5')).toBe(true)
    const date = field(SALES, 'fld_sale_date')
    expect(cleanField(date, '2026-02-28')).toEqual({ value: '2026-02-28' })
    expect(cleanField(date, '2026-02-30')).toEqual({ error: 'Must be a real date.' })
    const status = field(SALES, 'fld_sale_payment_status')
    expect(cleanField(status, 'paid')).toEqual({ value: 'paid' })
    expect('error' in cleanField(status, 'free')).toBe(true)
    const customer = field(SALES, 'fld_sale_customer')
    expect('error' in cleanField(customer, 'not-a-uuid')).toBe(true)
    expect(cleanField(customer, '0190F5E2-0000-7000-8000-000000000001')).toEqual({
      value: '0190f5e2-0000-7000-8000-000000000001',
    })
  })
})

describe('formSchema', () => {
  it('returns API values keyed by field ID, or field errors', () => {
    const schema = formSchema(table(CUSTOMERS))
    const ok = schema.safeParse({ fld_customer_name: 'Ada', fld_customer_phone: '0803', fld_customer_area: '', fld_customer_credit_limit: '2500' })
    expect(ok.success && ok.data).toEqual({
      fld_customer_name: 'Ada',
      fld_customer_phone: '0803',
      fld_customer_area: null,
      fld_customer_credit_limit: '2500.00',
    })
    const bad = schema.safeParse({ fld_customer_name: '' })
    expect(bad.success).toBe(false)
    expect(bad.error?.issues.map((i) => i.path[0])).toEqual(['fld_customer_name'])
  })
})

describe('form values', () => {
  it('round-trips a record and reports only changes', () => {
    const t = table(CUSTOMERS)
    const record = { fld_customer_name: 'Ada', fld_customer_phone: null, fld_customer_area: 'Yaba', fld_customer_credit_limit: '10.00' }
    expect(toFormValues(t, record).fld_customer_phone).toBe('')
    expect(changedValues(record, { ...record, fld_customer_area: 'Ikeja', fld_customer_phone: null })).toEqual({
      fld_customer_area: 'Ikeja',
    })
  })
})
