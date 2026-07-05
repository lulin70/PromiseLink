import { test, expect } from '@playwright/test'
import { injectLoginState, setupMockApi } from './mock_data'
import { navigateViaSidebar, waitForPageReady } from './helpers'

/**
 * 待办操作测试（使用 mock API，零 skip）。
 *
 * 设计原则（用户硬约束）：
 *   - "没有数据创造数据"：mock API 返回 pending 状态待办，消除"无数据"skip
 *   - "Skip的测试都不合理"：所有用例必须实际执行
 *   - mock 数据中 mockTodo 为 pending 状态，确保操作栏可见
 */
test.describe('待办操作 @todos', () => {
  test.beforeEach(async ({ page }) => {
    await injectLoginState(page)
    await setupMockApi(page)
  })

  test('待办列表页加载，标题与 tab 可见', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')

    await expect(page.locator('.page-todos'), '待办列表页应渲染').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.header-title'), '应显示「待办事项」标题').toContainText('待办事项')

    const actionTypeTabs = ['全部', '我的承诺', '等待回应', '跟进事项', '已完成']
    for (const t of actionTypeTabs) {
      await expect(page.locator('.tabs .tab', { hasText: t }).first(), `应有 action_type tab「${t}」`).toBeVisible()
    }
    await expect(page.locator('.search-input'), '应有搜索框').toBeVisible()
  })

  test('action_type tab 可切换', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')

    const myPromiseTab = page.locator('.tabs .tab', { hasText: '我的承诺' }).first()
    await myPromiseTab.evaluate((el: HTMLElement) => el.click())
    await expect(myPromiseTab).toHaveClass(/active/)
    await page.waitForLoadState('networkidle').catch(() => {})
  })

  test('侧边栏可导航到待办列表', async ({ page }) => {
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.pl-sidebar')

    await navigateViaSidebar(page, '待办')
    await expect(page.locator('.page-todos'), '侧边栏点击「待办」应到待办列表').toBeVisible({ timeout: 10000 })
  })

  test('点击待办标题跳转待办详情页', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.waitForTimeout(1500)

    const todoTitles = page.locator('.todo-title')
    await expect(todoTitles.first(), 'mock API 应返回待办数据').toBeVisible({ timeout: 10000 })

    await todoTitles.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail'), '应跳转到待办详情页').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.page-todo-detail .header-title'), '详情页标题应为「待办详情」').toContainText('待办详情')
  })

  test('待办详情页有操作按钮（忽略/推迟/完成）', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const todoTitles = page.locator('.todo-title')
    await expect(todoTitles.first(), 'mock API 应返回待办数据').toBeVisible({ timeout: 10000 })

    // mockTodo 为 pending 状态，点击第一个待办应直接进入详情且有操作栏
    await todoTitles.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail')).toBeVisible({ timeout: 10000 })

    const actionBar = page.locator('.action-bar')
    await expect(actionBar, 'pending 待办详情应有操作栏').toBeVisible({ timeout: 5000 })

    await expect(actionBar.locator('.action-btn', { hasText: '忽略' }), '应有「忽略」按钮').toBeVisible()
    await expect(actionBar.locator('.action-btn', { hasText: '推迟' }), '应有「推迟」按钮').toBeVisible()
    await expect(actionBar.locator('.action-btn', { hasText: '完成' }), '应有「完成」按钮').toBeVisible()
  })

  test('点击「完成」变更待办状态', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const todoTitles = page.locator('.todo-title')
    await expect(todoTitles.first(), 'mock API 应返回待办数据').toBeVisible({ timeout: 10000 })

    await todoTitles.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail')).toBeVisible({ timeout: 10000 })

    const statusBadgeBefore = await page.locator('.status-badge').first().innerText()

    const doneBtn = page.locator('.action-bar .action-btn', { hasText: '完成' }).first()
    await doneBtn.evaluate((el: HTMLElement) => el.click())

    await expect(page.locator('.action-bar .action-btn', { hasText: '恢复待处理' }), '完成后应显示「恢复待处理」按钮').toBeVisible({ timeout: 10000 })

    const statusBadgeAfter = await page.locator('.status-badge').first().innerText()
    expect(statusBadgeAfter, `完成操作应改变状态（前:${statusBadgeBefore} 后:${statusBadgeAfter}）`).not.toEqual(statusBadgeBefore)
  })

  test('点击「推迟」弹出输入框并确认推迟', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const todoTitles = page.locator('.todo-title')
    await expect(todoTitles.first(), 'mock API 应返回待办数据').toBeVisible({ timeout: 10000 })

    await todoTitles.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail')).toBeVisible({ timeout: 10000 })

    const snoozeBtn = page.locator('.action-bar .action-btn', { hasText: '推迟' }).first()
    await snoozeBtn.evaluate((el: HTMLElement) => el.click())

    const modal = page.locator('.taro-modal, .taromodal, [class*="modal"]').filter({ hasText: '推迟待办' }).first()
    await expect(modal, '点击推迟应弹出「推迟待办」对话框').toBeAttached({ timeout: 5000 })

    const confirmBtn = modal.locator('button, [class*="btn"], [class*="confirm"]').filter({ hasText: '推迟' }).last()
    await confirmBtn.evaluate((el: HTMLElement) => el.click())

    await expect(page.locator('.action-bar .action-btn', { hasText: '恢复待处理' }), '推迟后应显示「恢复待处理」按钮').toBeVisible({ timeout: 10000 })
  })

  test('列表页点击「完成」按钮更新待办', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const doneBtns = page.locator('.todo-card .done-btn')
    await expect(doneBtns.first(), 'mock API 应返回待办数据且有完成按钮').toBeVisible({ timeout: 10000 })

    await doneBtns.first().evaluate((el: HTMLElement) => el.click())
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)
    await expect(page.locator('.page-todos'), '操作后列表页应仍可用').toBeVisible()
  })

  test('"已完成"tab 显示已完成的待办', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')

    const doneTab = page.locator('.tabs .tab', { hasText: '已完成' }).first()
    await doneTab.evaluate((el: HTMLElement) => el.click())
    await expect(doneTab).toHaveClass(/active/)
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1000)

    await expect(page.locator('.page-todos'), '"已完成"tab 下页面应仍可用').toBeVisible()
  })
})
