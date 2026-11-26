import { expect, test } from '@playwright/test'

import { signIn, WS } from './helpers'

test('browse a table with search, a filter chip and sorting', async ({ page }) => {
  await signIn(page)
  await page.goto(`${WS}/tables/products`)
  await expect(page.getByRole('heading', { name: 'Products' })).toBeVisible()

  await page.getByRole('searchbox').fill('rice')
  await expect(page.getByRole('link', { name: 'Rice 50kg' }).first()).toBeVisible()
  await expect(page.getByRole('link', { name: 'Peak milk tin' })).toHaveCount(0)
  await page.getByRole('searchbox').fill('')

  await page.getByRole('button', { name: 'Add filter' }).click()
  await page.getByLabel('Field').selectOption({ label: 'Unit price' })
  await page.getByLabel('Condition').selectOption({ label: 'at least' })
  await page.getByLabel('Value').fill('9500')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.getByText('Unit price at least ₦9,500.00')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Peak milk tin' })).toHaveCount(0)
  await expect(page).toHaveURL(/filter=/)

  await page.getByRole('button', { name: 'Unit price', exact: true }).click()
  await expect(page.getByRole('columnheader', { name: 'Unit price' })).toHaveAttribute('aria-sort', 'ascending')
  await page.getByRole('button', { name: /Remove filter/ }).click()
  await expect(page.getByRole('link', { name: 'Peak milk tin' })).toBeVisible()
})

test('a record page shows its linked records and a shortcut to add one', async ({ page }) => {
  await signIn(page)
  await page.goto(`${WS}/tables/customers`)
  await page.getByRole('link', { name: 'Adaeze Okafor' }).first().click()
  await expect(page.getByRole('heading', { name: 'Adaeze Okafor' })).toBeVisible()
  await page.getByRole('link', { name: 'New sale for Adaeze Okafor' }).click()
  await expect(page.getByTestId('picked-customer')).toHaveText('Adaeze Okafor')
})
