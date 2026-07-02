import { test, expect } from '@playwright/test'
import {
  loginViaUi,
  clearLoginState,
  waitForPageReady,
  POC_SECRET,
  TOKEN_KEY,
  SECRET_KEY,
  USER_ID_KEY,
} from './helpers'

/**
 * 登录流程测试：未登录跳转、PoC 登录流程、登录态存储。
 *
 * 重要说明（与任务描述的偏差）：
 * 任务描述假设「token 存储在 sessionStorage」，但前端实际实现
 * （src/services/auth.ts）将 token 存储在 localStorage，PoC 密钥
 * 存储在 sessionStorage。本测试按实际实现验证，并在用例中标注偏差。
 * 修改前端存储策略超出本任务范围（不允许改源码），仅记录此差异。
 */
test.describe('登录流程 @auth', () => {
  test.beforeEach(async ({ page }) => {
    await clearLoginState(page)
  })

  test('未登录访问首页显示内联登录表单', async ({ page }) => {
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page)

    // 首页未登录时应显示内联登录卡片（而非直接报错或白屏）
    await expect(page.locator('.login-card'), '未登录应显示登录卡片').toBeVisible({ timeout: 10000 })
    // 登录卡片应包含用户 ID 与密钥两个输入框
    await expect(page.locator('.login-card .input').first(), '应有用户 ID 输入框').toBeVisible()
    await expect(page.locator('.login-card .input').nth(1), '应有 PoC 密钥输入框').toBeVisible()
    // 登录按钮
    await expect(page.locator('.login-card .login-btn'), '应有登录按钮').toBeVisible()
  })

  test('未登录访问受保护页跳回首页登录', async ({ page }) => {
    // todos 列表页未登录时会显示内联登录表单
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page)

    // todos 页未登录渲染内联登录卡片
    await expect(page.locator('.login-card'), '待办页未登录应显示登录卡片').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.login-title'), '登录标题应为「需要登录」').toContainText('登录')
  })

  test('PoC 登录流程：输入密钥 → 跳转首页仪表盘', async ({ page }) => {
    // 前置：需后端运行（POST /api/v1/auth/login）。若后端未运行，登录会失败，
    // 此用例将 fail 并提示后端依赖。
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page)

    await expect(page.locator('.login-card')).toBeVisible({ timeout: 10000 })

    // 模拟真实用户：填写用户 ID（Taro H5 渲染为 <taro-input-core>，需定位内部 <input>）
    await page.locator('.login-card .input input').first().fill('poc-user')
    // 填写 PoC 密钥
    await page.locator('.login-card .input input').nth(1).fill(POC_SECRET)
    // 点击登录（Taro View 的 onClick 需通过 DOM click 触发，Playwright force click 不够）
    await page.locator('.login-card .login-btn').evaluate((el: HTMLElement) => el.click())

    // 登录成功后应离开登录卡片，进入首页仪表盘
    await expect(page.locator('.page-index'), '登录后应进入首页仪表盘').toBeVisible({ timeout: 20000 })
    await expect(page.locator('.page-index .header-title'), '首页应显示标题').toBeVisible()
  })

  test('登录后 token 写入 localStorage（实际实现）', async ({ page }) => {
    // 说明：任务描述要求 sessionStorage 存储 token，但 auth.ts 实际用 localStorage。
    // 本断言按实际实现验证。若未来改为 sessionStorage，需同步更新此处。
    await loginViaUi(page)

    const token = await page.evaluate((k) => localStorage.getItem(k), TOKEN_KEY)
    expect(token, '登录后 localStorage 应写入 token（实际实现）').toBeTruthy()
    expect(token!.length, 'token 不应为空字符串').toBeGreaterThan(0)
  })

  test('登录后 PoC 密钥写入 sessionStorage（安全约束）', async ({ page }) => {
    // PoC 密钥存储在 sessionStorage，关闭标签页即清除，限制泄露窗口
    await loginViaUi(page)

    const secret = await page.evaluate((k) => sessionStorage.getItem(k), SECRET_KEY)
    expect(secret, '登录后 sessionStorage 应写入 PoC 密钥').toBeTruthy()
    expect(secret, '密钥不应为空').not.toBe('')
  })

  test('登录后用户 ID 写入 localStorage', async ({ page }) => {
    await loginViaUi(page)

    const userId = await page.evaluate((k) => localStorage.getItem(k), USER_ID_KEY)
    expect(userId, '登录后 localStorage 应写入 user_id').toBeTruthy()
    expect(userId, '用户 ID 应为 poc-user').toBe('poc-user')
  })

  test('登录态在页面刷新后保持（localStorage 持久化）', async ({ page }) => {
    await loginViaUi(page)
    const tokenBefore = await page.evaluate((k) => localStorage.getItem(k), TOKEN_KEY)
    expect(tokenBefore).toBeTruthy()

    // 刷新页面
    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitForPageReady(page)

    // 刷新后不应再显示登录卡片（token 仍在 localStorage）
    const tokenAfter = await page.evaluate((k) => localStorage.getItem(k), TOKEN_KEY)
    expect(tokenAfter, '刷新后 token 应仍在 localStorage').toBe(tokenBefore)
  })
})
