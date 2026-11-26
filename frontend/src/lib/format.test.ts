import { describe, expect, it } from 'vitest'

import { PRODUCTS, SALES, table } from '@/test/retail'

import { formatDate, formatMoney, formatValue } from './format'

describe('format', () => {
  it('formats money from the string, in naira', () => {
    expect(formatMoney('1200000.00')).toBe('₦1,200,000.00')
    // Beyond float precision: still exact.
    expect(formatMoney('12345678901234567.89')).toBe('₦12,345,678,901,234,567.89')
  })

  it('shows dates day-first without a timezone shift', () => {
    expect(formatDate('2026-11-24')).toBe('24 Nov 2026')
    expect(formatDate('2026-01-01')).toBe('1 Jan 2026')
  })

  it('formats enum labels and empty values', () => {
    const status = table(SALES).fields.find((f) => f.id === 'fld_sale_payment_status')!
    expect(formatValue(status, 'part_paid')).toBe('Part paid')
    const price = table(PRODUCTS).fields.find((f) => f.id === 'fld_product_unit_price')!
    expect(formatValue(price, null)).toBe('')
  })
})
