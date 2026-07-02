import { test, expect } from '@playwright/test'
import { loginViaUi, waitForPageReady, TOKEN_KEY } from './helpers'

/**
 * 跨页面跳转测试：验证事件/人脉/待办详情间的关联导航。
 *
 * 导航路径：
 *   1. 事件详情 → 点击关联人脉（EntityLink .entity-link-card）→ 人脉详情页
 *   2. 人脉详情 → 点击关联事件（EventLink .event-link-card）→ 事件详情页
 *   3. 待办详情 → 点击来源事件（EventLink .event-link-card）→ 事件详情页
 *   4. 人脉详情 → 点击关联待办（TodoLink .todo-link-card）→ 待办详情页
 *
 * 组件选择器（见 src/components/）：
 *   - EntityLink: .entity-link-card，点击 → navigateToEntityDetail → /pages/entities/detail
 *   - EventLink:  .event-link-card，点击 → navigateToEventDetail  → /pages/events/detail
 *   - TodoLink:   .todo-link-card，点击 → navigateToTodoDetail    → /pages/todos/detail
 *
 * 前置：需登录 + 后端运行且有关联数据。无数据时相关用例 skip。
 *
 * 说明：事件详情页/人脉详情页的关联数据由后端 Pipeline 异步生成，
 * 并非所有事件都有 related_entities。测试 1 通过 API 查找一个有
 * related_entities 的事件，再通过 URL 直接访问其详情页，确保跳转
 * 用例能在已有数据上稳定运行（而非依赖列表第一个事件是否有关联）。
 */
test.describe('跨页面跳转 @navigation', () => {
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page)
  })

  /**
   * 辅助：从事件列表进入第一个事件详情页（旧路径，保留供调试用）。
   * 当前测试 1 改用 findEventWithEntities + 直接访问 URL 的方式。
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

  /**
   * 辅助：通过后端 API 查找第一个有 related_entities 的事件 ID。
   * 在浏览器上下文中执行 fetch，自动携带 localStorage 中的 token。
   * 返回事件 ID 或 null（无关联数据时）。
   */
  async function findEventWithEntities(page: import('@playwright/test').Page): Promise<string | null> {
    return await page.evaluate(async (tokenKey) => {
      const token = localStorage.getItem(tokenKey)
      if (!token) return null
      const resp = await fetch('/api/v1/events?limit=100', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!resp.ok) return null
      const data = await resp.json()
      const items = Array.isArray(data) ? data : data.items || []
      // 优先找有 entities 字段的事件
      for (const e of items) {
        const ents = e.entities || []
        if (Array.isArray(ents) && ents.length > 0) return e.id
      }
      return null
    }, TOKEN_KEY)
  }

  test('事件详情 → 点击关联人脉 → 人脉详情页', async ({ page }) => {
    // 通过 API 找一个有 related_entities 的事件，确保跳转用例有数据支撑
    const eventId = await findEventWithEntities(page)
    test.skip(!eventId, '后端无带关联人脉的事件数据，跳过')

    // 直接访问该事件详情页 URL（navigation.ts: /pages/events/detail?id=xxx）
    await page.goto(`/pages/events/detail?id=${eventId}`, { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-event-detail')
    await expect(page.locator('.page-event-detail')).toBeVisible({ timeout: 10000 })

    // 事件详情页应有「关联人脉」分区，内含 EntityLink 卡片
    const entityLinks = page.locator('.entity-link-card')
    // 等待详情页 related_entities 异步加载（详情页在 useEffect 中调用 getEventDetail）
    await expect(entityLinks.first()).toBeVisible({ timeout: 8000 })
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
    // 等待 modal 出现 + getEntityDetail 异步加载完成（handleEntityTap 是异步的）
    const viewDetailBtn = page.locator('.view-detail-btn').first()
    await expect(viewDetailBtn).toBeVisible({ timeout: 8000 })
    test.skip((await viewDetailBtn.count()) === 0, '人脉 modal 无「查看完整详情」按钮，跳过')
    await viewDetailBtn.evaluate((el: HTMLElement) => el.click())

    await expect(page.locator('.page-entity-detail'), '应进入人脉详情页').toBeVisible({ timeout: 10000 })

    // 人脉详情页应有「相关事件」分区，内含 EventLink 卡片
    // history API 异步加载，等待 EventLink 渲染
    const eventLinks = page.locator('.event-link-card')
    await expect(eventLinks.first()).toBeVisible({ timeout: 10000 })
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
    // 等待 modal 出现 + getEntityDetail 异步加载完成
    await expect(viewDetailBtn).toBeVisible({ timeout: 8000 })
    test.skip((await viewDetailBtn.count()) === 0, '人脉 modal 无「查看完整详情」按钮，跳过')
    await viewDetailBtn.evaluate((el: HTMLElement) => el.click())

    await expect(page.locator('.page-entity-detail')).toBeVisible({ timeout: 10000 })

    const todoLinks = page.locator('.todo-link-card')
    // 等待 history API 异步加载 TodoLink 渲染
    await expect(todoLinks.first()).toBeVisible({ timeout: 10000 })
    const count = await todoLinks.count()
    test.skip(count === 0, '该人脉无关联待办，跳过跨页跳转用例')

    await todoLinks.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail'), '点击关联待办应跳转待办详情页').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.page-todo-detail .header-title'), '待办详情页标题应为「待办详情」').toContainText('待办详情')
  })
})
