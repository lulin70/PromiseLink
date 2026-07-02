import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright E2E configuration for PromiseLink frontend (Taro H5).
 *
 * 基础版为电脑宽屏两栏布局（≥1024px 触发桌面布局），
 * 因此 viewport 设为 1280x800 以模拟真实桌面用户使用场景。
 *
 * 运行方式：
 *   - 需要后端运行在 http://localhost:8000（健康检查 GET /api/v1/health）
 *   - webServer 会自动启动 Taro dev server（npm run dev:h5，端口 3000）
 *   - 仅运行 UI 用例：npx playwright test
 *   - 带界面运行：npm run test:e2e:headed
 *
 * 若后端不可用，测试仍会启动并尝试运行（用例会因 API 失败而 fail，
 * 但可验证 Playwright 配置本身是否正确、测试是否能启动）。
 */
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false, // Taro H5 dev server 单实例，避免端口/状态竞争
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // 单 worker：dev server 热重载状态 + sessionStorage 登录态隔离更稳定
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  expect: {
    timeout: 10000,
  },
  use: {
    baseURL: 'http://localhost:3000',
    // 基础版为电脑宽屏布局（≥1024px），使用桌面尺寸
    viewport: { width: 1280, height: 800 },
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
    // Taro H5 首屏需要加载 webpack bundle + 首次 API 调用，给足时间
    navigationTimeout: 30000,
    actionTimeout: 15000,
    locale: 'zh-CN',
  },
  projects: [
    {
      name: 'chromium-desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
  ],
  webServer: {
    command: 'npm run dev:h5',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120000, // Taro 首次编译较慢
    stdout: 'ignore',
    stderr: 'pipe',
  },
})
