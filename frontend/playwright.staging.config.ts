import { defineConfig, devices } from '@playwright/test'

/**
 * Staging E2E config — runs against deployed frontend.
 * Base URL from STAGING_BASE_URL env var (ICP备案前用临时IP, 备案后用正式域名).
 *
 * Run: STAGING_BASE_URL=https://gateway.promiselink.cn npx playwright test --config=playwright.staging.config.ts
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
    baseURL: process.env.STAGING_BASE_URL || 'https://gateway.promiselink.cn',
    viewport: { width: 1280, height: 800 },
    actionTimeout: 15000,
    navigationTimeout: 30000,
    ignoreHTTPSErrors: true,
  },
})
