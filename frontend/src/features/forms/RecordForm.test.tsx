import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { deleteUserDB, openUserDB } from '@/features/sync/db'
import { renderInWorkspace } from '@/test/render'
import { CUSTOMERS, PRODUCTS, retailSSD, SALES, table } from '@/test/retail'

import { RecordForm } from './RecordForm'

const RICE = '0190f5e2-0000-7000-8000-000000000001'
const ADA = '0190f5e2-0000-7000-8000-000000000002'

beforeEach(() => openUserDB('form-test'))
afterEach(async () => {
  vi.unstubAllGlobals()
  await deleteUserDB()
})

function renderSaleForm(onSubmit = vi.fn().mockResolvedValue(undefined)) {
  renderInWorkspace(<RecordForm ssd={retailSSD} table={table(SALES)} onSubmit={onSubmit} />, {
    lookups: {
      [PRODUCTS]: [{ id: RICE, title: 'Rice 50kg', version: 1 }],
      [CUSTOMERS]: [{ id: ADA, title: 'Adaeze Okafor', version: 1 }],
    },
  })
  return onSubmit
}

describe('RecordForm', () => {
  it('marks required fields and blocks an incomplete save', async () => {
    const onSubmit = renderSaleForm()
    expect(screen.getByLabelText(/Quantity/)).toHaveAttribute('aria-required', 'true')
    await userEvent.click(screen.getByRole('button', { name: /Save/ }))
    expect(onSubmit).not.toHaveBeenCalled()
    expect((await screen.findAllByText('This field is required.')).length).toBeGreaterThan(0)
  })

  it('defaults the sale date to today and submits canonical values', async () => {
    const onSubmit = renderSaleForm()
    const user = userEvent.setup()
    expect((screen.getByLabelText(/^Date/) as HTMLInputElement).value).toMatch(/^\d{4}-\d{2}-\d{2}$/)

    await user.click(screen.getByRole('combobox', { name: /Product/ }))
    await user.click(screen.getByRole('option', { name: 'Rice 50kg' }))
    await user.type(screen.getByLabelText(/Quantity/), '2')
    await user.type(screen.getByLabelText(/Unit price/), '45000')
    await user.type(screen.getByLabelText(/^Total/), '90,000')
    await user.selectOptions(screen.getByLabelText(/^Payment/), 'unpaid')
    await user.click(screen.getByRole('button', { name: /Save/ }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      fld_sale_product: RICE,
      fld_sale_quantity: 2,
      fld_sale_unit_price: '45000.00',
      fld_sale_total_amount: '90000.00',
      fld_sale_amount_paid: '0.00',
      fld_sale_payment_status: 'unpaid',
      fld_sale_customer: null,
    })
  })

  it('shows server errors on the right field', async () => {
    const onSubmit = vi.fn().mockResolvedValue({
      kind: 'invalid',
      recordId: 'x',
      message: 'Another record already has this value.',
      details: { fld_customer_phone: ['Another record already has this value.'] },
    })
    renderInWorkspace(<RecordForm ssd={retailSSD} table={table(CUSTOMERS)} onSubmit={onSubmit} />)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/Name/), 'Ada')
    await user.type(screen.getByLabelText(/Phone/), '0803')
    await user.click(screen.getByRole('button', { name: /Save/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Another record already has this value.')
    expect(screen.getByLabelText(/Phone/)).toHaveAttribute('aria-invalid', 'true')
  })

  it('creates a linked customer inline while offline and picks it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    renderSaleForm()
    const user = userEvent.setup()
    await user.click(screen.getByRole('combobox', { name: /Customer/ }))
    await user.click(screen.getByRole('option', { name: /New customer/ }))
    const inline = screen.getByRole('form', { name: 'Customer form' })
    await user.type(inline.querySelector('input')!, 'Bisi Market')
    await user.click(screen.getByRole('button', { name: 'Add customer' }))
    expect(await screen.findByTestId('picked-customer')).toHaveTextContent('Bisi Market')
  })
})
