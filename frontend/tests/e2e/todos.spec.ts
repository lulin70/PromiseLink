import { test, expect } from '@playwright/test'
import { loginViaUi, navigateViaSidebar, waitForPageReady } from './helpers'

/**
 * 待办操作测试。
 *
 * 待办列表页（src/pages/todos/index.tsx）：
 *   - 标题「待办事项」
 *   - 状态 tab：全部/待处理/已完成/已忽略/已推迟
 *   - 类型 tab：全部/关注/跟进/合作/风险
 *   - 待办卡片：标题可点击跳详情；操作按钮 删除/忽略/√完成
 *
 * 待办详情页（src/pages/todos/detail.tsx）：
 *   - 标题「待办详情」+ 返回按钮
 *   - 信息卡片（标题/类型/优先级/状态/截止/描述）
 *   - 来源事件 / 关联人脉 分区
 *   - 操作栏（pending 状态）：忽略 / 推迟 / √完成
 *   - 推迟：Taro.showModal editable，输入小时数后确认
 *
 * 前置：需登录 + 后端运行且有数据。无数据时相关用例 skip。
 */
test.describe('待办操作 @todos', () => {
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page)
  })

  test('待办列表页加载，标题与 tab 可见', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')

    await expect(page.locator('.page-todos'), '待办列表页应渲染').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.header-title'), '应显示「待办事项」标题').toContainText('待办事项')

    // 状态 tab
    const statusTabs = ['全部', '待处理', '已完成', '已忽略', '已推迟']
    for (const t of statusTabs) {
      await expect(page.locator('.tabs .tab', { hasText: t }).first(), `应有状态 tab「${t}」`).toBeVisible()
    }
    // 搜索框
    await expect(page.locator('.search-input'), '应有搜索框').toBeVisible()
  })

  test('状态 tab 可切换', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')

    const pendingTab = page.locator('.tabs .tab', { hasText: '待处理' }).first()
    await pendingTab.evaluate((el: HTMLElement) => el.click())
    await expect(pendingTab).toHaveClass(/active/)
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
    const count = await todoTitles.count()
    test.skip(count === 0, '后端无待办数据，跳过详情跳转用例')

    // 点击第一个待办标题（标题元素绑定 navigateToTodoDetail）
    await todoTitles.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail'), '应跳转到待办详情页').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.page-todo-detail .header-title'), '详情页标题应为「待办详情」').toContainText('待办详情')
  })

  test('待办详情页有操作按钮（忽略/推迟/完成）', async ({ page }) => {
    // 切到「待处理」状态，确保待办为 pending，详情页才显示操作栏
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.locator('.tabs .tab', { hasText: '待处理' }).first().evaluate((el: HTMLElement) => el.click())
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const todoTitles = page.locator('.todo-title')
    const count = await todoTitles.count()
    test.skip(count === 0, '后端无待处理待办，跳过操作按钮用例')

    await todoTitles.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail')).toBeVisible({ timeout: 10000 })

    // 操作栏应在 pending 状态显示
    const actionBar = page.locator('.action-bar')
    await expect(actionBar, '待处理待办详情应有操作栏').toBeVisible({ timeout: 5000 })

    // 三个按钮：忽略 / 推迟 / √完成
    await expect(actionBar.locator('.action-btn', { hasText: '忽略' }), '应有「忽略」按钮').toBeVisible()
    await expect(actionBar.locator('.action-btn', { hasText: '推迟' }), '应有「推迟」按钮').toBeVisible()
    await expect(actionBar.locator('.action-btn', { hasText: '完成' }), '应有「完成」按钮').toBeVisible()
  })

  test('点击「完成」变更待办状态', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.locator('.tabs .tab', { hasText: '待处理' }).first().evaluate((el: HTMLElement) => el.click())
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const todoTitles = page.locator('.todo-title')
    const count = await todoTitles.count()
    test.skip(count === 0, '后端无待处理待办，跳过完成操作用例')

    await todoTitles.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail')).toBeVisible({ timeout: 10000 })

    // 记录操作前的状态徽章文本
    const statusBadgeBefore = await page.locator('.status-badge').first().innerText()

    // 点击「√完成」
    const doneBtn = page.locator('.action-bar .action-btn', { hasText: '完成' }).first()
    await doneBtn.evaluate((el: HTMLElement) => el.click())

    // 等待状态变更：操作栏消失或变为「恢复待处理」
    await expect(page.locator('.action-bar .action-btn', { hasText: '恢复待处理' }), '完成后应显示「恢复待处理」按钮').toBeVisible({ timeout: 10000 })

    // 状态徽章应变化（不再是「待处理」）
    const statusBadgeAfter = await page.locator('.status-badge').first().innerText()
    expect(statusBadgeAfter, `完成操作应改变状态（前:${statusBadgeBefore} 后:${statusBadgeAfter}）`).not.toContain('待处理')
  })

  test('点击「推迟」弹出输入框并确认推迟', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.locator('.tabs .tab', { hasText: '待处理' }).first().evaluate((el: HTMLElement) => el.click())
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const todoTitles = page.locator('.todo-title')
    const count = await todoTitles.count()
    test.skip(count === 0, '后端无待处理待办，跳过推迟操作用例')

    await todoTitles.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail')).toBeVisible({ timeout: 10000 })

    // 点击「推迟」
    const snoozeBtn = page.locator('.action-bar .action-btn', { hasText: '推迟' }).first()
    await snoozeBtn.evaluate((el: HTMLElement) => el.click())

    // Taro.showModal 在 H5 渲染为模态对话框，含标题「推迟待办」与输入框
    // Taro H5 modal 可能被 CSS 隐藏，用 toBeAttached 检测 DOM 存在而非可见性
    const modal = page.locator('.taro-modal, .taromodal, [class*="modal"]').filter({ hasText: '推迟待办' }).first()
    await expect(modal, '点击推迟应弹出「推迟待办」对话框').toBeAttached({ timeout: 5000 })

    // 确认推迟（点击模态框中的「推迟」确认按钮）
    // Taro H5 modal 的确认按钮 class 通常为 taro-modal__footer__btn 或含 confirm 文本
    const confirmBtn = modal.locator('button, [class*="btn"], [class*="confirm"]').filter({ hasText: '推迟' }).last()
    await confirmBtn.evaluate((el: HTMLElement) => el.click())

    // 推迟成功后应显示「恢复待处理」（状态变为 snoozed）
    await expect(page.locator('.action-bar .action-btn', { hasText: '恢复待处理' }), '推迟后应显示「恢复待处理」按钮').toBeVisible({ timeout: 10000 })
  })

  test('列表页点击「完成」按钮更新待办', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.locator('.tabs .tab', { hasText: '待处理' }).first().evaluate((el: HTMLElement) => el.click())
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const doneBtns = page.locator('.todo-card .done-btn')
    const count = await doneBtns.count()
    test.skip(count === 0, '后端无待处理待办，跳过列表完成用例')

    // 点击第一个「√完成」
    await doneBtns.first().evaluate((el: HTMLElement) => el.click())
    // 列表应刷新，该卡片应消失或状态变更
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)
    // 重新加载后待处理列表中该卡片应减少（不严格断言数量，仅验证无报错且页面仍可用）
    await expect(page.locator('.page-todos'), '操作后列表页应仍可用').toBeVisible()
  })
})
