import { test, expect } from '@playwright/test'
import { attachErrorCollectors, waitForPageReady } from './helpers'

/**
 * 首页加载测试：确保页面能打开（不白屏、不 404），
 * 标题/导航可见，无 console 错误，无网络请求失败。
 *
 * 这是"用户到手页面打不开"问题的第一道防线。
 */
test.describe('首页加载 @home', () => {
  test('首页可访问，不白屏不 404', async ({ page }) => {
    const { consoleErrors, failedRequests, filterRealErrors } = attachErrorCollectors(page)

    const response = await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    // 不 404：HTTP 状态码应为 2xx（Taro H5 dev server 返回 200）
    expect(response, '首页应返回 HTTP 响应').not.toBeNull()
    expect(response!.status(), `首页不应 404，实际状态码 ${response!.status()}`).toBeLessThan(400)

    await waitForPageReady(page)

    // 不白屏：body 应有实质内容
    const bodyText = await page.locator('body').innerText()
    expect(bodyText.trim().length, '页面不应白屏（body 应有文本内容）').toBeGreaterThan(0)

    // 首页应包含 PromiseLink 品牌字样（标题或侧边栏）
    expect(bodyText, '应包含 PromiseLink 品牌字样').toContain('PromiseLink')
  })

  test('桌面侧边栏导航可见', async ({ page }) => {
    // viewport 1280x800 ≥1024px，应显示桌面侧边栏
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.pl-sidebar, .page-index')

    // 桌面侧边栏应可见
    const sidebar = page.locator('.pl-sidebar')
    await expect(sidebar, '≥1024px 应显示桌面侧边栏').toBeVisible({ timeout: 10000 })

    // 侧边栏应包含 5 个导航项 + 我的
    const navLabels = ['首页', '事件', '人脉', '待办', '承诺']
    for (const label of navLabels) {
      await expect(
        sidebar.locator('.pl-nav-item', { hasText: label }).first(),
        `侧边栏应包含导航项「${label}」`,
      ).toBeVisible()
    }
    // 品牌区
    await expect(sidebar.locator('.pl-brand-text')).toContainText('PromiseLink')
  })

  test('无 console 错误（良性错误除外）', async ({ page }) => {
    const { consoleErrors, filterRealErrors } = attachErrorCollectors(page)

    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page)
    // 给首屏 API 调用一点时间触发可能的错误
    await page.waitForTimeout(2000)

    const realErrors = filterRealErrors(consoleErrors)
    expect(
      realErrors,
      `不应有 console 错误（实际：${realErrors.join(' | ')}）`,
    ).toHaveLength(0)
  })

  test('无失败的网络请求（前端资源）', async ({ page }) => {
    const { failedRequests } = attachErrorCollectors(page)

    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page)
    await page.waitForTimeout(2000)

    // 后端 API 失败（如 8000 未启动）会导致请求失败，这里只关注前端资源类失败
    // 过滤掉 /api/v1 开头的请求（后端问题由后端测试覆盖）
    const frontendFailures = failedRequests.filter((r) => !r.includes('/api/v1'))
    expect(
      frontendFailures,
      `前端资源请求不应失败（实际失败：${frontendFailures.join(' | ')}）`,
    ).toHaveLength(0)
  })

  test('未登录时显示内联登录表单', async ({ page }) => {
    // 清除可能存在的登录态
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => {
      localStorage.removeItem('promiselink_token')
      localStorage.removeItem('promiselink_user_id')
      sessionStorage.removeItem('promiselink_poc_secret')
    })
    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitForPageReady(page)

    // 未登录应显示登录卡片
    await expect(page.locator('.login-card'), '未登录应显示登录卡片').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.login-title'), '登录卡片应含 PromiseLink 标题').toContainText('PromiseLink')
  })
})
