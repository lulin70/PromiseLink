import { test, expect } from '@playwright/test'
import { injectLoginState, setupMockApi, MOCK_EVENT_ID, MOCK_ENTITY_ID } from './mock_data'
import { waitForPageReady } from './helpers'

/**
 * 跨页面跳转测试（使用 mock API，零 skip）。
 *
 * 设计原则（用户硬约束）：
 *   - "没有数据创造数据"：mock API 返回完整关联数据（事件↔人脉↔待办↔承诺）
 *   - "Skip的测试都不合理"：所有跳转用例必须实际执行
 *   - mock 数据中 event/entity/todo 互相引用，确保关联导航可测
 */
test.describe('跨页面跳转 @navigation', () => {
  test.beforeEach(async ({ page }) => {
    await injectLoginState(page)
    await setupMockApi(page)
  })

  test('事件详情 → 点击关联人脉 → 人脉详情页', async ({ page }) => {
    // mock API 对 /events/{id} 返回包含 parsed_data.entities 的事件
    await page.goto(`/pages/events/detail?id=${MOCK_EVENT_ID}`, { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-event-detail')
    await expect(page.locator('.page-event-detail')).toBeVisible({ timeout: 10000 })

    // 事件详情页应有「关联人脉」分区，内含 EntityLink 卡片
    const entityLinks = page.locator('.entity-link-card')
    await expect(entityLinks.first(), 'mock 事件应有关联人脉').toBeVisible({ timeout: 10000 })

    await entityLinks.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-entity-detail'), '点击关联人脉应跳转人脉详情页').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.page-entity-detail .header-title'), '人脉详情页标题应为「人脉详情」').toContainText('人脉详情')
  })

  test('人脉详情 → 点击关联事件 → 事件详情页', async ({ page }) => {
    await page.goto('/pages/entities/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-entities')
    await page.waitForTimeout(1500)

    const entityCards = page.locator('.entity-card')
    await expect(entityCards.first(), 'mock API 应返回人脉数据').toBeVisible({ timeout: 10000 })

    await entityCards.first().evaluate((el: HTMLElement) => el.click())
    const viewDetailBtn = page.locator('.view-detail-btn').first()
    await expect(viewDetailBtn, '人脉 modal 应有「查看完整详情」按钮').toBeVisible({ timeout: 8000 })
    await viewDetailBtn.evaluate((el: HTMLElement) => el.click())

    await expect(page.locator('.page-entity-detail'), '应进入人脉详情页').toBeVisible({ timeout: 10000 })

    // mock API 对 /entities/{id}/history 返回关联事件
    const eventLinks = page.locator('.event-link-card')
    await expect(eventLinks.first(), 'mock 人脉应有关联事件').toBeVisible({ timeout: 10000 })

    await eventLinks.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-event-detail'), '点击关联事件应跳转事件详情页').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.page-event-detail .header-title'), '事件详情页标题应为「事件详情」').toContainText('事件详情')
  })

  test('待办详情 → 点击来源事件 → 事件详情页', async ({ page }) => {
    await page.goto('/pages/todos/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-todos')
    await page.waitForTimeout(1500)

    const todoTitles = page.locator('.todo-title')
    await expect(todoTitles.first(), 'mock API 应返回待办数据').toBeVisible({ timeout: 10000 })

    await todoTitles.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail'), '应进入待办详情页').toBeVisible({ timeout: 10000 })

    // mock 待办有 event_id 字段，详情页应渲染来源事件 EventLink
    const eventLinks = page.locator('.event-link-card')
    await expect(eventLinks.first(), 'mock 待办应有来源事件').toBeVisible({ timeout: 10000 })

    await eventLinks.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-event-detail'), '点击来源事件应跳转事件详情页').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.page-event-detail .header-title'), '事件详情页标题应为「事件详情」').toContainText('事件详情')
  })

  test('人脉详情 → 点击关联待办 → 待办详情页', async ({ page }) => {
    await page.goto('/pages/entities/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-entities')
    await page.waitForTimeout(1500)

    const entityCards = page.locator('.entity-card')
    await expect(entityCards.first(), 'mock API 应返回人脉数据').toBeVisible({ timeout: 10000 })

    await entityCards.first().evaluate((el: HTMLElement) => el.click())
    const viewDetailBtn = page.locator('.view-detail-btn').first()
    await expect(viewDetailBtn, '人脉 modal 应有「查看完整详情」按钮').toBeVisible({ timeout: 8000 })
    await viewDetailBtn.evaluate((el: HTMLElement) => el.click())

    await expect(page.locator('.page-entity-detail')).toBeVisible({ timeout: 10000 })

    // mock API 对 /entities/{id}/history 返回关联待办
    const todoLinks = page.locator('.todo-link-card')
    await expect(todoLinks.first(), 'mock 人脉应有关联待办').toBeVisible({ timeout: 10000 })

    await todoLinks.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-todo-detail'), '点击关联待办应跳转待办详情页').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.page-todo-detail .header-title'), '待办详情页标题应为「待办详情」').toContainText('待办详情')
  })
})
