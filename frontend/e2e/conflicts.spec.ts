import { expect, test, type Browser } from '@playwright/test'

import { goOffline, goOnline, pill, signIn, unique, uniquePhone, waitForServiceWorker, WS } from './helpers'

async function device(browser: Browser) {
  const context = await browser.newContext()
  const page = await context.newPage()
  await signIn(page)
  await waitForServiceWorker(page)
  return { context, page }
}

async function openProduct(page: import('@playwright/test').Page, name: string) {
  await page.goto(`${WS}/tables/products`)
  await page.getByRole('searchbox').fill(name)
  await page.getByRole('link', { name }).first().click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
}

test('the same record edited on two devices: the user sees both versions and chooses', async ({ browser }) => {
  const shop = await device(browser)
  const phone = await device(browser)
  const product = unique('Garri bag')

  // Create the product online and open it on the phone so it is cached.
  await shop.page.goto(`${WS}/forms/products`)
  await shop.page.getByLabel(/Name/).fill(product)
  await shop.page.getByLabel(/Product code/).fill(unique('SKU').replace(' ', '-'))
  await shop.page.getByLabel(/Category/).selectOption('provisions')
  await shop.page.getByLabel(/Unit price/).fill('15000')
  await shop.page.getByLabel(/^In stock/).fill('20')
  await shop.page.getByRole('button', { name: 'Save product' }).click()
  await expect(shop.page.getByText('Product saved.')).toBeVisible()
  await openProduct(phone.page, product)

  // The phone goes offline and changes the stock to 18.
  await goOffline(phone.context, phone.page)
  await phone.page.getByRole('link', { name: 'Edit' }).click()
  await phone.page.getByLabel(/^In stock/).fill('18')
  await phone.page.getByRole('button', { name: 'Save' }).click()
  await expect(phone.page.getByText(/saved on this device/)).toBeVisible()

  // Meanwhile the shop computer changes it to 25.
  await shop.page.getByRole('link', { name: 'Edit' }).click()
  await shop.page.getByLabel(/^In stock/).fill('25')
  await shop.page.getByRole('button', { name: 'Save' }).click()
  await expect(shop.page).not.toHaveURL(/\/edit$/)
  await expect(shop.page.getByRole('main')).toContainText('25')

  // The phone reconnects: a conflict, not a silent overwrite.
  await goOnline(phone.context)
  await expect(pill(phone.page)).toHaveText('Needs attention', { timeout: 15_000 })
  await pill(phone.page).click()
  const card = phone.page.getByText('Changed elsewhere').locator('xpath=ancestor::div[contains(@class,"rounded-lg")][1]')
  await expect(card.getByRole('row', { name: /In stock/ })).toContainText('18')
  await expect(card.getByRole('row', { name: /In stock/ })).toContainText('25')

  await phone.page.getByRole('button', { name: 'Keep my change' }).click()
  await expect(phone.page.getByText('Everything is synced')).toBeVisible({ timeout: 15_000 })

  await shop.page.reload()
  await expect(shop.page.getByRole('main')).toContainText('18')
  await shop.context.close()
  await phone.context.close()
})

test('a duplicate unique value created offline on two devices: one is rejected and fixed', async ({ browser }) => {
  const first = await device(browser)
  const second = await device(browser)
  const phone = uniquePhone()

  for (const d of [first, second]) {
    await d.page.goto(`${WS}/forms/customers`)
    await expect(d.page.getByRole('button', { name: 'Save customer' })).toBeVisible()
    await goOffline(d.context, d.page)
    await d.page.getByLabel(/Name/).fill(unique('Customer'))
    await d.page.getByLabel(/Phone/).fill(phone)
    await d.page.getByRole('button', { name: 'Save customer' }).click()
    await expect(d.page.getByText(/saved on this device/)).toBeVisible()
  }

  await goOnline(first.context)
  await expect(pill(first.page)).toHaveText('Online', { timeout: 15_000 })

  await goOnline(second.context)
  await expect(pill(second.page)).toHaveText('Needs attention', { timeout: 15_000 })
  await pill(second.page).click()
  await expect(second.page.getByText('Not accepted')).toBeVisible()
  await expect(second.page.getByText(/Phone: Another record already has this value/)).toBeVisible()

  // Fix and resend with another number.
  await second.page.getByRole('button', { name: 'Fix and resend' }).click()
  await second.page.getByLabel(/Phone/).fill(uniquePhone())
  await second.page.getByRole('button', { name: 'Save and sync' }).click()
  await expect(second.page.getByText('Everything is synced')).toBeVisible({ timeout: 15_000 })
  await first.context.close()
  await second.context.close()
})
