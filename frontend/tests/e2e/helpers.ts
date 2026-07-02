import { Page, expect } from '@playwright/test'

/**
 * E2E 测试辅助工具：登录、导航、等待策略。
 *
 * 说明：
 * - 登录 token 实际存储在 localStorage（key: promiselink_token），
 *   PoC 密钥存储在 sessionStorage（key: promiselink_poc_secret）。
 *   （见 src/services/auth.ts，基础版当前实现如此。）
 * - 基础版为电脑宽屏布局，桌面侧边栏导航在 ≥1024px 时显示。
 */

// PoC 登录密钥（与 scripts/e2e/e2e_browser_test.py 保持一致）
export const POC_SECRET = process.env.PROMISELINK_POC_SECRET || 'promiselink2026'
export const POC_USER_ID = 'poc-user'

// localStorage / sessionStorage keys（与 src/services/auth.ts 保持一致）
export const TOKEN_KEY = 'promiselink_token'
export const USER_ID_KEY = 'promiselink_user_id'
export const SECRET_KEY = 'promiselink_poc_secret'

// 桌面侧边栏导航项（与 src/app.tsx NAV_ITEMS 一致）
export const NAV_ITEMS = [
  { path: '/pages/index/index', label: '首页' },
  { path: '/pages/events/index', label: '事件' },
  { path: '/pages/entities/index', label: '人脉' },
  { path: '/pages/todos/index', label: '待办' },
  { path: '/pages/promises/index', label: '承诺' },
] as const

/**
 * 等待页面网络空闲 + 关键元素可见。
 * Taro H5 首屏需加载 webpack bundle 并发起首次 API 调用，
 * 单纯 waitUntil('networkidle') 不足以保证 React 已渲染，故叠加元素等待。
 */
export async function waitForPageReady(page: Page, elementSelector = 'body') {
  await page.waitForLoadState('domcontentloaded')
  await page.waitForLoadState('networkidle').catch(() => {
    // networkidle 可能因长轮询/心跳请求超时，降级为 domcontentloaded
  })
  await page.waitForSelector(elementSelector, { state: 'visible', timeout: 15000 }).catch(() => {
    // 元素未可见也不致命，由具体断言决定成败
  })
}

/**
 * 通过 UI 操作完成 PoC 登录（首页内联登录表单）。
 *
 * 首页未登录时会渲染内联登录卡片：
 *   - 用户 ID 输入框（placeholder 'poc-user'）
 *   - PoC 密钥输入框（type 'safe-password'，placeholder '请输入 PoC Secret'）
 *   - 登录按钮（文本 '登 录'）
 *
 * 登录成功后 token 写入 localStorage，密钥写入 sessionStorage。
 */
export async function loginViaUi(page: Page, userId = POC_USER_ID, secret = POC_SECRET) {
  // 前往首页，未登录会显示内联登录表单
  await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
  await waitForPageReady(page, '.login-card, .page-index')

  // 若已在登录态则直接返回
  const token = await page.evaluate((k) => localStorage.getItem(k), TOKEN_KEY)
  if (token) return

  // 等待登录卡片出现
  await page.waitForSelector('.login-card', { state: 'visible', timeout: 10000 })

  // 填写用户 ID（Taro H5 渲染为 <taro-input-core class="input">，内部含 <input>）
  const userIdInput = page.locator('.login-card .input input').first()
  await userIdInput.fill(userId)

  // 填写 PoC 密钥（type=safe-password，Taro H5 渲染为 password input）
  const secretInput = page.locator('.login-card .input input').nth(1)
  await secretInput.fill(secret)

  // 点击登录按钮（Taro View 的 onClick 需通过 DOM click 触发）
  await page.locator('.login-card .login-btn').evaluate((el: HTMLElement) => el.click())

  // 等待登录完成：token 写入 localStorage 或首页仪表盘出现
  await expect
    .poll(async () => {
      const t = await page.evaluate((k) => localStorage.getItem(k), TOKEN_KEY)
      return !!t
    }, { timeout: 15000, message: '登录后应在 localStorage 写入 token' })
    .toBeTruthy()

  // 等待首页仪表盘渲染（summary cards / header）
  await page.waitForSelector('.page-index .header, .summary-cards, .header-title', {
    state: 'visible',
    timeout: 15000,
  }).catch(() => {
    // 仪表盘可能因后端无数据而显示空状态，token 存在即视为登录成功
  })
}

/**
 * 直接注入登录态（绕过 UI），用于不需要验证登录流程本身的用例。
 * 注意：此方式不写入 sessionStorage 的密钥，故 401 自动重登不可用；
 * 仅适合纯导航/渲染验证。需要完整登录态请用 loginViaUi。
 */
export async function injectLoginState(page: Page, token = 'mock-token-for-nav', userId = POC_USER_ID) {
  await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
  await page.evaluate(
    ({ t, u, tk, uk }) => {
      localStorage.setItem(tk, t)
      localStorage.setItem(uk, u)
    },
    { t: token, u: userId, tk: TOKEN_KEY, uk: USER_ID_KEY },
  )
}

/**
 * 清除登录态，确保用例间隔离。
 */
export async function clearLoginState(page: Page) {
  // 确保页面已导航到有效 URL，避免 about:blank 的 localStorage 访问被拒绝
  if (page.url() === 'about:blank' || !page.url().startsWith('http')) {
    await page.goto('/', { waitUntil: 'domcontentloaded' })
  }
  await page.evaluate(({ tk, uk, sk }) => {
    localStorage.removeItem(tk)
    localStorage.removeItem(uk)
    sessionStorage.removeItem(sk)
  }, { tk: TOKEN_KEY, uk: USER_ID_KEY, sk: SECRET_KEY })
}

/**
 * 通过桌面侧边栏点击导航到目标 tab 页。
 * 模拟真实用户点击，而非直接访问 URL。
 */
export async function navigateViaSidebar(page: Page, label: string) {
  // 桌面侧边栏在 ≥1024px 显示
  await page.waitForSelector('.pl-sidebar', { state: 'visible', timeout: 10000 })
  const navItem = page.locator('.pl-nav-item', { hasText: label }).first()
  await navItem.evaluate((el: HTMLElement) => el.click())
  // 等待路由切换 + 页面渲染
  await page.waitForLoadState('networkidle').catch(() => {})
}

/**
 * 收集页面 console 错误与失败网络请求，供断言使用。
 * 返回清理函数（用于在测试结束时移除监听）。
 */
export function attachErrorCollectors(page: Page) {
  const consoleErrors: string[] = []
  const failedRequests: string[] = []

  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('requestfailed', (req) => {
    failedRequests.push(`${req.method()} ${req.url()}`)
  })

  return {
    consoleErrors,
    failedRequests,
    // 允许的"良性"错误（如 favicon 404、热重载相关），断言时过滤
    filterRealErrors: (errs: string[]) =>
      errs.filter(
        (e) =>
          !e.includes('favicon') &&
          !e.includes('webpack') &&
          !e.includes('HMR') &&
          !e.includes('hot-update'),
      ),
  }
}
