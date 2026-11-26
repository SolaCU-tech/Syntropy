import { describe, expect, it } from 'vitest'

import { SALES, table } from '@/test/retail'

import { cleanFilterValue, describeFilter, parseFilters, serializeFilters } from './filters'

describe('filters', () => {
  const sales = table(SALES)
  const total = sales.fields.find((f) => f.id === 'fld_sale_total_amount')!

  it('round-trips through the URL as the query AST where-shape', () => {
    const filters = [{ field: total.id, op: 'gte', value: '1000.00' }]
    const raw = serializeFilters(filters)
    expect(JSON.parse(raw!)).toEqual({ all: filters })
    expect(parseFilters(raw)).toEqual(filters)
    expect(parseFilters('not json')).toEqual([])
    expect(serializeFilters([])).toBeNull()
  })

  it('describes chips in owner language', () => {
    expect(describeFilter(sales, { field: total.id, op: 'gte', value: '1000.00' })).toBe('Total at least ₦1,000.00')
    expect(describeFilter(sales, { field: 'fld_sale_date', op: 'lt', value: '2026-11-01' })).toBe('Date before 1 Nov 2026')
    expect(describeFilter(sales, { field: 'fld_sale_customer', op: 'is_empty' })).toBe('Customer is empty')
  })

  it('validates values with the form rules, minus ranges', () => {
    expect(cleanFilterValue(total, '-5')).toEqual({ value: '-5.00' })
    expect('error' in cleanFilterValue(total, 'lots')).toBe(true)
  })
})
