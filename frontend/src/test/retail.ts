import retail from '../../../backend/apps/schema_registry/examples/retail.ssd.json'

import type { SSD } from '@/lib/ssd'

/** The hand-written retail SSD the backend validates, so frontend tests use the real thing. */
export const retailSSD = { ...retail, version: 1, status: 'published' } as unknown as SSD

export const CUSTOMERS = 'tbl_customers'
export const PRODUCTS = 'tbl_products'
export const SALES = 'tbl_sales'

export function table(id: string) {
  return retailSSD.tables.find((t) => t.id === id)!
}
