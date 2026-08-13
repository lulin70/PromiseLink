import { test, expect } from '@playwright/test'
import {
  loginViaUi,
  clearLoginState,
  waitForPageReady,
  POC_SECRET,
  TOKEN_KEY,
  USER_ID_KEY,
} from './helpers'

/**
 * 登录流程测试（v0.9.7 身份统一）。
 *
 * v0.9.7 起基础版为单用户本地应用，LoginGate 在挂载时自动调用 /auth/auto，
 * 打开即用、无需密钥。本文件验证：
 *   - 自动登录主流程：打开首页直接进入仪表盘，token/user_id 写入 localStorage
 *   - PoC/dev 模式回退：当 /auth/auto 不可用（如返回 404）时仍显示密钥登录表单
 *
 * 说明：
 * - token 存储在 localStorage（src/services/auth.ts 实际实现）。
 * - 自动登录不写入 sessionStorage 的 PoC 密钥（无需密钥）。
 */
test.describe('登录流程 @auth', () => {
  test.beforeEach(async ({ page }) => {
    await clearLoginState(page)
  })

  test('自动登录：打开首页直接进入仪表盘（无需密钥）', async ({ page }) => {
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page)

    // /auth/auto 自动登录成功后 token 写入 localStorage
    await expect
      .poll(() => page.evaluate((k) => localStorage.getItem(k), TOKEN_KEY), {
        timeout: 15000,
        message: '自动登录后应写入 token',
      })
      .toBeTruthy()

    // 进入首页仪表盘
    await expect(page.locator('.page-index'), '自动登录后应进入首页仪表盘').toBeVisible({ timeout: 15000 })
  })

  test('自动登录后 token 写入 localStorage', async ({ page }) => {
    await loginViaUi(page)

    const token = await page.evaluate((k) => localStorage.getItem(k), TOKEN_KEY)
    expect(token, '登录后 localStorage 应写入 token').toBeTruthy()
    expect(token!.length, 'token 不应为空字符串').toBeGreaterThan(0)
  })

  test('自动登录后 user_id 写入 localStorage = local_user', async ({ page }) => {
    await loginViaUi(page)

    const userId = await page.evaluate((k) => localStorage.getItem(k), USER_ID_KEY)
    expect(userId, '登录后 localStorage 应写入 user_id').toBeTruthy()
    expect(userId, '单用户本地身份应为 local_user').toBe('local_user')
  })

  test('PoC 模式回退：/auth/auto 不可用时显示密钥登录表单', async ({ page }) => {
    // 模拟 /auth/auto 不可用（如后端未开启自动登录），LoginGate 应回退到表单
    await page.route('**/api/v1/auth/auto', (route) =>
      route.fulfill({ status: 404, body: JSON.stringify({ detail: 'not found' }) })
    )
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page)

    // 回退到密钥登录表单
    await expect(page.locator('.login-card'), '自动登录不可用时显示密钥登录表单').toBeVisible({ timeout: 10000 })
    // 登录卡片应包含用户 ID 与密钥两个输入框
    await expect(page.locator('.login-card .input').first(), '应有用户 ID 输入框').toBeVisible()
    await expect(page.locator('.login-card .input').nth(1), '应有 PoC 密钥输入框').toBeVisible()

    // PoC 回退仍可完成登录
    await page.locator('.login-card .input input').first().fill('local_user')
    await page.locator('.login-card .input input').nth(1).fill(POC_SECRET)
    await page.locator('.login-card .login-btn').evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-index'), 'PoC 回退登录后应进入首页仪表盘').toBeVisible({ timeout: 20000 })
  })
})
