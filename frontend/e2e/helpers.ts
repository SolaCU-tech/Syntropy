import { expect, type BrowserContext, type Page } from '@playwright/test'

export const USER = process.env.E2E_USER ?? 'demo'
export const PASSWORD = process.env.E2E_PASSWORD ?? 'demo-pass-1'
export const WS = '/w/ades-provisions-example'

export function unique(prefix: string): string {
  return `${prefix} ${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`
}

/** A phone number nobody else in the test data has. */
export function uniquePhone(): string {
  return `0809${String(Date.now()).slice(-7)}`
}

export async function signIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Username').fill(USER)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/w\/[^/]+\/home/)
}

/** Wait until the service worker controls the page, so the app shell opens offline. */
export async function waitForServiceWorker(page: Page) {
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready
  })
  // The first load isn't controlled yet; a reload is.
  await page.reload()
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true)
}

/** Open the screens a phone would have visited, so they're cached for offline use. */
export async function warmUp(page: Page) {
  for (const path of ['home', 'tables', 'tables/sales', 'tables/customers', 'tables/products', 'forms/sales']) {
    await page.goto(`${WS}/${path}`)
    await expect(page.getByRole('main')).toBeVisible()
    await page.waitForLoadState('networkidle')
  }
}

export async function goOffline(context: BrowserContext, page: Page) {
  await context.setOffline(true)
  await expect(page.getByTestId('sync-pill')).toContainText('Offline')
}

export async function goOnline(context: BrowserContext) {
  await context.setOffline(false)
}

export function pill(page: Page) {
  return page.getByTestId('sync-pill')
}
