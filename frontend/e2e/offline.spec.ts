import { expect, test } from '@playwright/test'

import { goOffline, goOnline, pill, signIn, unique, uniquePhone, waitForServiceWorker, warmUp, WS } from './helpers'

test('records a sale offline with a new customer, survives a reload, and syncs later', async ({ page, context }) => {
  await signIn(page)
  await waitForServiceWorker(page)
  await warmUp(page)

  await goOffline(context, page)

  // The app shell opens with no connection (PWA), still signed in.
  await page.reload()
  await expect(pill(page)).toContainText('Offline')

  const customer = unique('Funke Stores')
  await page.goto(`${WS}/forms/sales`).catch(() => undefined)
  await page.getByRole('combobox', { name: /Product/ }).click()
  await page.getByRole('option', { name: 'Rice 50kg' }).click()

  // A new customer created inline while recording the sale.
  await page.getByRole('combobox', { name: /Customer/ }).click()
  await page.getByRole('option', { name: /New customer/ }).click()
  const inline = page.getByRole('form', { name: 'Customer form' })
  await inline.getByLabel(/Name/).fill(customer)
  await inline.getByLabel(/Phone/).fill(uniquePhone())
  await inline.getByRole('button', { name: 'Add customer' }).click()
  await expect(page.getByTestId('picked-customer')).toHaveText(customer)

  await page.getByLabel(/Quantity/).fill('2')
  await page.getByLabel(/Unit price/).fill('45000')
  await page.getByLabel(/^Total/).fill('90000')
  await page.getByRole('button', { name: 'Save sale' }).click()

  await expect(page.getByText(/saved on this device/)).toBeVisible()
  await expect(page.getByText('Not synced yet')).toBeVisible()
  await expect(pill(page)).toContainText('Offline (2 waiting)')

  // Nothing is lost across a reload while offline.
  await page.reload()
  await expect(pill(page)).toContainText('Offline (2 waiting)')
  await page.getByTestId('sync-pill').click()
  await expect(page.getByRole('heading', { name: 'Waiting to sync' })).toBeVisible()
  await expect(page.getByText(`New customer: ${customer}`)).toBeVisible()

  // Back online: the queue uploads and empties.
  await goOnline(context)
  await expect(pill(page)).toHaveText('Online', { timeout: 15_000 })
  await expect(page.getByText('Everything is synced')).toBeVisible()

  // The server has both records, linked.
  await page.goto(`${WS}/tables/customers`)
  await page.getByRole('searchbox').fill(customer)
  await page.getByRole('link', { name: customer }).first().click()
  await expect(page.getByRole('heading', { name: customer })).toBeVisible()
  await expect(page.getByText('Not synced yet')).toHaveCount(0)
  const sales = page.getByTestId('linked-sales')
  await expect(sales.getByRole('heading')).toHaveText('Sales1')
  await expect(sales.getByText('₦90,000.00')).toBeVisible()
})
