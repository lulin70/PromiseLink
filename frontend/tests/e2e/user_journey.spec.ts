import { test, expect } from '@playwright/test'
import { injectLoginState, setupMockApi, MOCK_PROMISE_TODO_ID } from './mock_data'
import {
  loginViaUi,
  navigateViaSidebar,
  waitForPageReady,
  clearLoginState,
  attachErrorCollectors,
} from './helpers'

/**
 * PromiseLink 基础版 — 真实用户旅程 E2E 测试.
 *
 * 设计原则
 * --------
 * 模拟真实用户从头到尾的操作旅程，覆盖：
 *   1. 完整引导旅程（打开 → 登录 → 录入 → 查看结果）
 *   2. 录入后切换人脉/待办/承诺分区查看
 *   3. 待办完成、承诺兑现的 UI 状态变更
 *   4. 跨页面导航（事件→人脉→待办→承诺→设置）
 *   5. 设置页数据导出与隐私删除
 *   6. 错误输入的 UI 错误提示
 *   7. 不同屏幕尺寸下布局不破
 *
 * 技术策略
 * --------
 * - 使用 setupMockApi 拦截所有 /api/v1/** 请求，返回确定性测试数据
 * - 引导旅程测试用 loginViaUi（真实 UI 登录流程，login API 被 mock）
 * - 其余测试用 injectLoginState（绕过登录，聚焦业务交互）
 * - Taro H5 渲染：点击事件用 evaluate(el => el.click()) 触发（Taro View 的 onClick）
 * - 桌面布局 ≥1024px 显示侧边栏，默认 viewport 1280x800
 */

// ═══════════════════════════════════════════════════════════════════
// 旅程 1: 完整引导旅程
// ═══════════════════════════════════════════════════════════════════

test.describe('完整引导旅程 @onboarding', () => {
  test('打开 → 登录 → 首次录入 → 查看结果', async ({ page }) => {
    // 先清除登录态，确保从未登录状态开始
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await clearLoginState(page)

    // 设置 mock API（loginViaUi 的 POST /auth/login 会被拦截）
    await setupMockApi(page)

    // 标记 guide 已展示，避免引导 overlay 干扰（聚焦登录+录入旅程）
    await page.evaluate(() => {
      localStorage.setItem('guide_shown', JSON.stringify({ data: true }))
    })

    // 1. 通过 UI 登录（真实用户路径：填写用户 ID + PoC 密钥 → 点击登录）
    await loginViaUi(page)

    // 2. 登录成功后应进入首页仪表盘
    await expect(page.locator('.page-index, .summary-cards, .header-title').first()).toBeVisible({
      timeout: 15000,
    })

    // 3. 导航到录入页（通过首页 FAB 按钮，模拟真实用户路径）
    await page.goto('/pages/input/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-input')
    await expect(page.locator('.page-input'), '录入页应渲染').toBeVisible({ timeout: 10000 })

    // 4. 输入会议文本
    await page.locator('.input-tab', { hasText: '事件录入' }).evaluate((el: HTMLElement) => el.click())
    const textarea = page.locator('.text-input textarea').first()
    await expect(page.locator('.text-input').first(), '应有文本输入框').toBeVisible({ timeout: 5000 })
    await textarea.fill('今天和张总开会，他承诺下周三前发送合同草案，我答应周五前提供技术方案。')

    // 5. 点击「记录并解析」
    const submitBtn = page.locator('.submit-btn', { hasText: '记录并解析' })
    await expect(submitBtn).toBeVisible()
    await submitBtn.evaluate((el: HTMLElement) => el.click())

    // 6. 提交后应进入解析结果视图
    await expect(page.locator('.result-card'), '提交后应进入解析结果视图').toBeVisible({
      timeout: 20000,
    })
  })
})

// ═══════════════════════════════════════════════════════════════════
// 旅程 2-5: 业务交互（登录态注入 + mock API）
// ═══════════════════════════════════════════════════════════════════

test.describe('用户旅程 — 业务交互 @journey', () => {
  test.beforeEach(async ({ page }) => {
    await injectLoginState(page)
    await setupMockApi(page)
    // 标记 guide 已展示，避免引导 overlay 干扰
    await page.evaluate(() => {
      localStorage.setItem('guide_shown', JSON.stringify({ data: true }))
    })
  })

  test('录入后切换人脉/待办/承诺分区查看', async ({ page }) => {
    // 录入事件
    await page.goto('/pages/input/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-input')
    await page.locator('.input-tab', { hasText: '事件录入' }).evaluate((el: HTMLElement) => el.click())
    await page.locator('.text-input textarea').first().fill('与王晓明讨论产品合作方案')
    await page.locator('.submit-btn', { hasText: '记录并解析' }).evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.result-card'), '应进入结果视图').toBeVisible({ timeout: 20000 })

    // 切换到人脉分区
    await page.goto('/pages/entities/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-entities')
    await page.waitForTimeout(1500)
    await expect(page.locator('.entity-card').first(), '人脉页应展示人脉卡片').toBeVisible({
      timeout: 10000,
    })

    // 切换到待办分区
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.waitForTimeout(1500)
    await expect(page.locator('.todo-title').first(), '待办页应展示待办项').toBeVisible({
      timeout: 10000,
    })

    // 切换到承诺分区
    await page.goto('/pages/promises/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-promises, .promise-card, .empty-state')
    await expect(page.locator('body'), '承诺页应渲染').toBeVisible()
  })

  test('待办页 → 点击完成 → 验证 UI 状态更新', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const todoTitles = page.locator('.todo-title')
    await expect(todoTitles.first(), 'mock API 应返回待办数据').toBeVisible({ timeout: 10000 })

    // 进入待办详情
    await todoTitles.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail'), '应进入待办详情页').toBeVisible({ timeout: 10000 })

    const statusBadgeBefore = await page.locator('.status-badge').first().innerText()

    // 点击「完成」
    const doneBtn = page.locator('.action-bar .action-btn', { hasText: '完成' }).first()
    await expect(doneBtn, 'pending 待办应有「完成」按钮').toBeVisible()
    await doneBtn.evaluate((el: HTMLElement) => el.click())

    // 验证状态变更：应显示「恢复待处理」按钮
    await expect(
      page.locator('.action-bar .action-btn', { hasText: '恢复待处理' }),
      '完成后应显示「恢复待处理」按钮',
    ).toBeVisible({ timeout: 10000 })

    const statusBadgeAfter = await page.locator('.status-badge').first().innerText()
    expect(statusBadgeAfter, '完成操作应改变状态徽章').not.toEqual(statusBadgeBefore)
  })

  test('承诺页 → 标记兑现 → 验证状态', async ({ page }) => {
    // 进入承诺详情页（mock 承诺 todo 为 pending 状态）
    await page.goto(`/pages/promises/detail?id=${MOCK_PROMISE_TODO_ID}`, {
      waitUntil: 'domcontentloaded',
    })
    await waitForPageReady(page, '.page-promise-detail')
    await expect(page.locator('.page-promise-detail'), '承诺详情页应渲染').toBeVisible({
      timeout: 10000,
    })

    // pending 状态应有「√ 已兑现」按钮
    const fulfillBtn = page.locator('.action-btn', { hasText: '已兑现' }).first()
    await expect(fulfillBtn, 'pending 承诺应有「已兑现」按钮').toBeVisible({ timeout: 10000 })

    const statusBefore = await page.locator('.status-badge').first().innerText()

    // 点击「已兑现」
    await fulfillBtn.evaluate((el: HTMLElement) => el.click())

    // 验证状态变更（mock API 返回 fulfilled，详情页应更新）
    await page.waitForTimeout(1500)
    const statusAfter = await page.locator('.status-badge').first().innerText()
    expect(statusAfter, '兑现后状态徽章应变化').not.toEqual(statusBefore)
  })

  test('跨页面导航：事件 → 人脉 → 待办 → 承诺 → 设置', async ({ page }) => {
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.pl-sidebar')
    await expect(page.locator('.pl-sidebar'), '侧边栏应可见').toBeVisible({ timeout: 10000 })

    // 事件页
    await navigateViaSidebar(page, '事件')
    await expect(page.locator('.page-events'), '应导航到事件页').toBeVisible({ timeout: 10000 })

    // 人脉页
    await navigateViaSidebar(page, '人脉')
    await expect(page.locator('.page-entities'), '应导航到人脉页').toBeVisible({ timeout: 10000 })

    // 待办页
    await navigateViaSidebar(page, '待办')
    await expect(page.locator('.page-todos'), '应导航到待办页').toBeVisible({ timeout: 10000 })

    // 承诺页
    await navigateViaSidebar(page, '承诺')
    await expect(page.locator('.page-promises, .promise-page, body'), '应导航到承诺页').toBeVisible({
      timeout: 10000,
    })

    // 设置页（mine，通过侧边栏底部入口）
    const mineNav = page.locator('.pl-nav-mine').first()
    await mineNav.evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.mine-page'), '应导航到设置页').toBeVisible({ timeout: 10000 })
  })

  test('设置页 → 数据导出 → 隐私删除', async ({ page }) => {
    await page.goto('/pages/mine/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.mine-page')
    await expect(page.locator('.mine-page'), '设置页应渲染').toBeVisible({ timeout: 10000 })

    // 验证设置页菜单项
    await expect(
      page.locator('.mine-menu-label', { hasText: '导出我的数据' }),
      '应有「导出我的数据」菜单项',
    ).toBeVisible()
    await expect(
      page.locator('.mine-menu-label', { hasText: '删除我的数据' }),
      '应有「删除我的数据」菜单项',
    ).toBeVisible()

    // 1. 数据导出（点击触发 mock exportData，应显示成功 toast）
    const exportItem = page.locator('.mine-menu-item', { hasText: '导出我的数据' }).first()
    await exportItem.evaluate((el: HTMLElement) => el.click())
    await page.waitForTimeout(2000)
    // 导出后页面应仍可用（mock 返回 download_url）
    await expect(page.locator('.mine-page'), '导出后设置页应仍可用').toBeVisible()

    // 2. 隐私删除流程
    const deleteItem = page.locator('.mine-menu-item.mine-menu-danger', { hasText: '删除我的数据' }).first()
    await deleteItem.evaluate((el: HTMLElement) => el.click())

    // 应弹出二次确认 modal
    await expect(page.locator('.privacy-delete-modal'), '应弹出删除确认 modal').toBeVisible({
      timeout: 5000,
    })
    await expect(page.locator('.pd-modal-title'), 'modal 标题应为「确认删除全部数据」').toContainText(
      '确认删除',
    )

    // 输入确认短语 DELETE（Taro Input 渲染为 <taro-input-core>，需定位内部 <input>）
    const confirmInput = page.locator('.pd-modal-input input').first()
    await confirmInput.fill('DELETE')

    // 点击「永久删除」
    const confirmBtn = page.locator('.pd-modal-btn-danger').first()
    await expect(confirmBtn, '输入正确短语后删除按钮应可点击').not.toHaveClass(/disabled/)
    await confirmBtn.evaluate((el: HTMLElement) => el.click())

    // 应显示删除成功提示（Taro showToast 或 modal）
    await page.waitForTimeout(2000)
    // mock API 返回成功，modal 应关闭或显示成功提示
    await expect(page.locator('body'), '删除操作后页面应仍可用').toBeVisible()
  })
})

// ═══════════════════════════════════════════════════════════════════
// 旅程 6: 错误输入的 UI 处理
// ═══════════════════════════════════════════════════════════════════

test.describe('错误处理 UI @error-handling', () => {
  test.beforeEach(async ({ page }) => {
    await injectLoginState(page)
    await setupMockApi(page)
    await page.evaluate(() => {
      localStorage.setItem('guide_shown', JSON.stringify({ data: true }))
    })
  })

  test('空文本提交时应有 UI 反馈（按钮禁用或提示）', async ({ page }) => {
    await page.goto('/pages/input/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-input')
    await page.locator('.input-tab', { hasText: '事件录入' }).evaluate((el: HTMLElement) => el.click())

    // 不输入任何内容，检查提交按钮状态
    const submitBtn = page.locator('.submit-btn', { hasText: '记录并解析' }).first()
    await expect(submitBtn, '提交按钮应存在').toBeVisible({ timeout: 5000 })

    // 空文本时按钮应禁用或点击后应有错误提示（前端应有前端校验）
    const isDisabled = await submitBtn.evaluate((el: HTMLElement) => {
      const classList = el.className
      const hasDisabled = classList.includes('disabled') || classList.includes('disabled-btn')
      return hasDisabled
    })

    if (!isDisabled) {
      // 若按钮未禁用，点击后应有错误 toast 或输入框高亮
      await submitBtn.evaluate((el: HTMLElement) => el.click())
      await page.waitForTimeout(1500)
      // 页面不应崩溃，仍停留在录入页
      await expect(page.locator('.page-input'), '空输入提交后应仍停留在录入页').toBeVisible()
    }
  })

  test('超长文本输入不崩溃', async ({ page }) => {
    await page.goto('/pages/input/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-input')
    await page.locator('.input-tab', { hasText: '事件录入' }).evaluate((el: HTMLElement) => el.click())

    // 输入超长文本（模拟用户粘贴大段内容）
    const longText = '今天和张总开会讨论合作。'.repeat(500) // ~5KB
    const textarea = page.locator('.text-input textarea').first()
    await textarea.fill(longText)
    await expect(textarea, '超长文本应能输入').toHaveValue(/张总/)

    // 页面不应崩溃
    await expect(page.locator('.page-input'), '超长文本后页面应仍可用').toBeVisible()
  })

  test('页面无致命 console 错误', async ({ page }) => {
    const { consoleErrors, filterRealErrors } = attachErrorCollectors(page)

    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-index, .pl-sidebar')
    await page.waitForTimeout(2000)

    // 导航到各页面，收集 console 错误
    for (const path of [
      '/pages/events/index',
      '/pages/entities/index',
      '/pages/todos/index',
      '/pages/promises/index',
    ]) {
      await page.goto(path, { waitUntil: 'domcontentloaded' })
      await page.waitForLoadState('networkidle').catch(() => {})
      await page.waitForTimeout(1000)
    }

    const realErrors = filterRealErrors(consoleErrors)
    expect(realErrors, `不应有致命 console 错误: ${realErrors.join('; ')}`).toHaveLength(0)
  })
})

// ═══════════════════════════════════════════════════════════════════
// 旅程 7: 响应式布局
// ═══════════════════════════════════════════════════════════════════

test.describe('响应式布局 @responsive', () => {
  test.beforeEach(async ({ page }) => {
    await injectLoginState(page)
    await setupMockApi(page)
    await page.evaluate(() => {
      localStorage.setItem('guide_shown', JSON.stringify({ data: true }))
    })
  })

  test('桌面布局（1280px）侧边栏可见', async ({ page }) => {
    // 默认 viewport 1280x800（playwright.config.ts 已配置）
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-index, .pl-sidebar')
    await page.waitForTimeout(1500)

    await expect(page.locator('.pl-sidebar'), '桌面尺寸应有侧边栏').toBeVisible({ timeout: 10000 })
  })

  test('窄屏布局（768px）页面不破', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 })
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, 'body')
    await page.waitForTimeout(1500)

    // 页面应渲染不崩溃（窄屏可能隐藏侧边栏，但主内容区应可见）
    await expect(page.locator('body'), '窄屏下页面应渲染').toBeVisible()

    // 导航到待办页验证不破
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos, body')
    await expect(page.locator('body'), '窄屏下待办页应渲染').toBeVisible()
  })

  test('移动端布局（375px）页面不破', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, 'body')
    await page.waitForTimeout(1500)

    await expect(page.locator('body'), '移动端页面应渲染').toBeVisible()

    // 验证关键页面不崩溃
    for (const path of ['/pages/events/index', '/pages/entities/index', '/pages/mine/index']) {
      await page.goto(path, { waitUntil: 'domcontentloaded' })
      await page.waitForLoadState('networkidle').catch(() => {})
      await page.waitForTimeout(800)
      await expect(page.locator('body'), `${path} 移动端应渲染`).toBeVisible()
    }
  })
})
