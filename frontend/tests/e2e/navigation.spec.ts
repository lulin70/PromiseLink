import { test, expect } from '@playwright/test'
import { loginViaUi, waitForPageReady } from './helpers'

/**
 * 跨页面跳转测试：验证事件/人脉/待办详情间的关联导航。
 *
 * 导航路径：
 *   1. 事件详情 → 点击关联人脉（EntityLink .entity-link-card）→ 人脉详情页
 *   2. 人脉详情 → 点击关联事件（EventLink .event-link-card）→ 事件详情页
 *   3. 待办详情 → 点击来源事件（EventLink .event-link-card）→ 事件详情页
 *
 * 组件选择器（见 src/components/）：
 *   - EntityLink: .entity-link-card，点击 → navigateToEntityDetail → /pages/entities/detail
 *   - EventLink:  .event-link-card，点击 → navigateToEventDetail  → /pages/events/detail
 *   - TodoLink:   .todo-link-card，点击 → navigateToTodoDetail    → /pages/todos/detail
 *
 * 前置：需登录 + 后端运行且有关联数据。无数据时相关用例 skip。
 */
test.describe('跨页面跳转 @navigation', () => {
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page)
  })

  /**
   * 辅助：从事件列表进入第一个事件详情页。
   * 返回事件详情页是否成功打开。
   */
  async function openFirstEventDetail(page: import('@playwright/test').Page): Promise<boolean> {
    await page.goto('/pages/events/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-events')
    // 切「全部」筛选最大化有数据概率
    await page.locator('.filter-tab', { hasText: '全部' }).first().evaluate((el: HTMLElement) => el.click())
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const eventCards = page.locator('.event-card')
    if ((await eventCards.count()) === 0) return false

    await eventCards.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.event-detail, .detail-row').first()).toBeVisible({ timeout: 5000 })

    const viewDetailBtn = page.locator('.view-detail-btn').first()
    if ((await viewDetailBtn.count()) === 0) return false

    await viewDetailBtn.evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-event-detail')).toBeVisible({ timeout: 10000 })
    return true
  }

  test('事件详情 → 点击关联人脉 → 人脉详情页', async ({ page }) => {
    const opened = await openFirstEventDetail(page)
    test.skip(!opened, '后端无事件数据或无法进入事件详情，跳过')

    // 事件详情页应有「关联人脉」分区，内含 EntityLink 卡片
    const entityLinks = page.locator('.entity-link-card')
    const count = await entityLinks.count()
    test.skip(count === 0, '该事件无关联人脉，跳过跨页跳转用例')

    // 点击第一个关联人脉
    await entityLinks.first().evaluate((el: HTMLElement) => el.click())

    // 应跳转到人脉详情页
    await expect(page.locator('.page-entity-detail'), '点击关联人脉应跳转人脉详情页').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.page-entity-detail .header-title'), '人脉详情页标题应为「人脉详情」').toContainText('人脉详情')
  })

  test('人脉详情 → 点击关联事件 → 事件详情页', async ({ page }) => {
    // 先进入人脉列表，打开第一个人脉详情页
    await page.goto('/pages/entities/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-entities')
    await page.waitForTimeout(1500)

    const entityCards = page.locator('.entity-card')
    const listCount = await entityCards.count()
    test.skip(listCount === 0, '后端无人脉数据，跳过')

    // 人脉列表点击会打开 modal；点击「查看完整详情」进入人脉详情页
    await entityCards.first().evaluate((el: HTMLElement) => el.click())
    const viewDetailBtn = page.locator('.view-detail-btn').first()
    test.skip((await viewDetailBtn.count()) === 0, '人脉 modal 无「查看完整详情」按钮，跳过')
    await viewDetailBtn.evaluate((el: HTMLElement) => el.click())

    await expect(page.locator('.page-entity-detail'), '应进入人脉详情页').toBeVisible({ timeout: 10000 })

    // 人脉详情页应有「相关事件」分区，内含 EventLink 卡片
    const eventLinks = page.locator('.event-link-card')
    const count = await eventLinks.count()
    test.skip(count === 0, '该人脉无关联事件，跳过跨页跳转用例')

    // 点击第一个关联事件
    await eventLinks.first().evaluate((el: HTMLElement) => el.click())

    // 应跳转到事件详情页
    await expect(page.locator('.page-event-detail'), '点击关联事件应跳转事件详情页').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.page-event-detail .header-title'), '事件详情页标题应为「事件详情」').toContainText('事件详情')
  })

  test('待办详情 → 点击来源事件 → 事件详情页', async ({ page }) => {
    // 进入待办列表，打开第一个待办详情
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.waitForTimeout(1500)

    const todoTitles = page.locator('.todo-title')
    const count = await todoTitles.count()
    test.skip(count === 0, '后端无待办数据，跳过')

    await todoTitles.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail'), '应进入待办详情页').toBeVisible({ timeout: 10000 })

    // 待办详情页应有「来源事件」分区，内含 EventLink 卡片
    const eventLinks = page.locator('.event-link-card')
    const eventCount = await eventLinks.count()
    test.skip(eventCount === 0, '该待办无来源事件，跳过跨页跳转用例')

    // 点击来源事件
    await eventLinks.first().evaluate((el: HTMLElement) => el.click())

    // 应跳转到事件详情页
    await expect(page.locator('.page-event-detail'), '点击来源事件应跳转事件详情页').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.page-event-detail .header-title'), '事件详情页标题应为「事件详情」').toContainText('事件详情')
  })

  test('人脉详情 → 点击关联待办 → 待办详情页', async ({ page }) => {
    // 附加：人脉详情的关联待办跳转
    await page.goto('/pages/entities/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-entities')
    await page.waitForTimeout(1500)

    const entityCards = page.locator('.entity-card')
    test.skip((await entityCards.count()) === 0, '后端无人脉数据，跳过')

    await entityCards.first().evaluate((el: HTMLElement) => el.click())
    const viewDetailBtn = page.locator('.view-detail-btn').first()
    test.skip((await viewDetailBtn.count()) === 0, '人脉 modal 无「查看完整详情」按钮，跳过')
    await viewDetailBtn.evaluate((el: HTMLElement) => el.click())

    await expect(page.locator('.page-entity-detail')).toBeVisible({ timeout: 10000 })

    const todoLinks = page.locator('.todo-link-card')
    const count = await todoLinks.count()
    test.skip(count === 0, '该人脉无关联待办，跳过跨页跳转用例')

    await todoLinks.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail'), '点击关联待办应跳转待办详情页').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.page-todo-detail .header-title'), '待办详情页标题应为「待办详情」').toContainText('待办详情')
  })
})
