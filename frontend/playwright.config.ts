import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end tests for the demo journey and offline entry (spec section 21).
 * They expect the built app on vite preview (port 4173) proxying /api to a Django server
 * seeded with `python manage.py seed_demo`; CI starts both (see .github/workflows/ci.yml).
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:4173',
    trace: 'off',
    serviceWorkers: 'allow',
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : undefined,
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'phone', use: { ...devices['Pixel 7'] }, testMatch: /offline\.spec\.ts/ },
  ],
})
