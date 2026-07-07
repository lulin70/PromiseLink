import { defineConfig, devices } from '@playwright/test'

/**
 * Staging E2E config — runs against deployed frontend at http://47.116.219.15
 * No webServer (uses deployed frontend), no API mock (uses real backend).
 *
 * Run: npx playwright test --config=playwright.staging.config.ts
 */
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: 'list',
  expect: { timeout: 15000 },
  use: {
    baseURL: 'http://47.116.219.15',
    viewport: { width: 1280, height: 800 },
    actionTimeout: 15000,
    navigationTimeout: 30000,
    ignoreHTTPSErrors: true,
  },
})
