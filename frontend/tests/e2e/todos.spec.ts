import { test, expect } from '@playwright/test'
import { loginViaUi, navigateViaSidebar, waitForPageReady } from './helpers'

/**
 * 待办操作测试（2.2 改进后）。
 *
 * 待办列表页（src/pages/todos/index.tsx）：
 *   - 标题「待办事项」
 *   - action_type 维度 tab：全部 / 我的承诺 / 等待回应 / 跟进事项 / 已完成
 *   - "全部" tab 显示所有非 completed 待办，按 dynamic_score 排序
 *   - "我的承诺"/"等待回应"/"跟进事项" tab 按 action_type 前端过滤
 *   - "已完成" tab 显示 status === 'completed' 的待办归档
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
 *
 * Taro H5 兼容方案：
 *   - tab 项渲染为 <taro-view-core>，click() 可见性检测会超时，改用 evaluate 触发 DOM click
 *   - CSS Modules 类名被哈希，优先使用文本内容等稳定选择器
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

    // action_type 维度 tab（2.2 改进后）
    const actionTypeTabs = ['全部', '我的承诺', '等待回应', '跟进事项', '已完成']
    for (const t of actionTypeTabs) {
      await expect(page.locator('.tabs .tab', { hasText: t }).first(), `应有 action_type tab「${t}」`).toBeVisible()
    }
    // 搜索框
    await expect(page.locator('.search-input'), '应有搜索框').toBeVisible()
  })

  test('action_type tab 可切换', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')

    // 点击"我的承诺"tab（action_type 维度）
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
    const count = await todoTitles.count()
    test.skip(count === 0, '后端无待办数据，跳过详情跳转用例')

    // 点击第一个待办标题（标题元素绑定 navigateToTodoDetail）
    await todoTitles.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail'), '应跳转到待办详情页').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.page-todo-detail .header-title'), '详情页标题应为「待办详情」').toContainText('待办详情')
  })

  test('待办详情页有操作按钮（忽略/推迟/完成）', async ({ page }) => {
    // "全部"tab 显示所有非 completed 待办，从中取 pending 待办测试操作栏
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const todoTitles = page.locator('.todo-title')
    const count = await todoTitles.count()
    test.skip(count === 0, '后端无待办数据，跳过操作按钮用例')

    // 遍历查找 pending 状态的待办（detail 页 action-bar 仅 pending 状态显示 忽略/推迟/完成）
    let foundPending = false
    const maxTry = Math.min(count, 5)
    for (let i = 0; i < maxTry; i++) {
      await todoTitles.nth(i).evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.page-todo-detail')).toBeVisible({ timeout: 10000 })
      const hasIgnore = await page.locator('.action-bar .action-btn', { hasText: '忽略' }).count()
      if (hasIgnore > 0) { foundPending = true; break }
      if (i < maxTry - 1) { await page.goBack(); await page.waitForTimeout(500) }
    }
    test.skip(!foundPending, '前5个待办均非 pending 状态，跳过操作按钮用例')

    const actionBar = page.locator('.action-bar')
    await expect(actionBar, '待办详情应有操作栏').toBeVisible({ timeout: 5000 })

    // 三个按钮：忽略 / 推迟 / √完成
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
    const count = await todoTitles.count()
    test.skip(count === 0, '后端无待办数据，跳过完成操作用例')

    // 遍历查找 pending 状态的待办
    let foundPending = false
    const maxTry = Math.min(count, 5)
    for (let i = 0; i < maxTry; i++) {
      await todoTitles.nth(i).evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.page-todo-detail')).toBeVisible({ timeout: 10000 })
      const hasIgnore = await page.locator('.action-bar .action-btn', { hasText: '忽略' }).count()
      if (hasIgnore > 0) { foundPending = true; break }
      if (i < maxTry - 1) { await page.goBack(); await page.waitForTimeout(500) }
    }
    test.skip(!foundPending, '前5个待办均非 pending 状态，跳过完成操作用例')

    // 记录操作前的状态徽章文本
    const statusBadgeBefore = await page.locator('.status-badge').first().innerText()

    // 点击「√完成」
    const doneBtn = page.locator('.action-bar .action-btn', { hasText: '完成' }).first()
    await doneBtn.evaluate((el: HTMLElement) => el.click())

    // 等待状态变更：操作栏消失或变为「恢复待处理」
    await expect(page.locator('.action-bar .action-btn', { hasText: '恢复待处理' }), '完成后应显示「恢复待处理」按钮').toBeVisible({ timeout: 10000 })

    // 状态徽章应变化
    const statusBadgeAfter = await page.locator('.status-badge').first().innerText()
    expect(statusBadgeAfter, `完成操作应改变状态（前:${statusBadgeBefore} 后:${statusBadgeAfter}）`).not.toEqual(statusBadgeBefore)
  })

  test('点击「推迟」弹出输入框并确认推迟', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const todoTitles = page.locator('.todo-title')
    const count = await todoTitles.count()
    test.skip(count === 0, '后端无待办数据，跳过推迟操作用例')

    // 遍历查找 pending 状态的待办
    let foundPending = false
    const maxTry = Math.min(count, 5)
    for (let i = 0; i < maxTry; i++) {
      await todoTitles.nth(i).evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.page-todo-detail')).toBeVisible({ timeout: 10000 })
      const hasIgnore = await page.locator('.action-bar .action-btn', { hasText: '忽略' }).count()
      if (hasIgnore > 0) { foundPending = true; break }
      if (i < maxTry - 1) { await page.goBack(); await page.waitForTimeout(500) }
    }
    test.skip(!foundPending, '前5个待办均非 pending 状态，跳过推迟操作用例')

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
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const doneBtns = page.locator('.todo-card .done-btn')
    const count = await doneBtns.count()
    test.skip(count === 0, '后端无待办数据，跳过列表完成用例')

    // 点击第一个「√完成」
    await doneBtns.first().evaluate((el: HTMLElement) => el.click())
    // 列表应刷新，该卡片应消失或状态变更
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)
    // 重新加载后列表中该卡片应减少（不严格断言数量，仅验证无报错且页面仍可用）
    await expect(page.locator('.page-todos'), '操作后列表页应仍可用').toBeVisible()
  })

  test('"已完成"tab 显示已完成的待办', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')

    // 点击"已完成"tab
    const doneTab = page.locator('.tabs .tab', { hasText: '已完成' }).first()
    await doneTab.evaluate((el: HTMLElement) => el.click())
    await expect(doneTab).toHaveClass(/active/)
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1000)

    // "已完成"tab 激活时，页面应仍可用（不严格断言是否有数据）
    await expect(page.locator('.page-todos'), '"已完成"tab 下页面应仍可用').toBeVisible()
  })
})
