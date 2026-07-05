import { test, expect } from '@playwright/test'
import { injectLoginState, setupMockApi } from './mock_data'
import { navigateViaSidebar, waitForPageReady } from './helpers'

/**
 * 事件列表与详情测试（使用 mock API，零 skip）。
 *
 * 设计原则（用户硬约束）：
 *   - "没有数据创造数据"：通过 setupMockApi 拦截 API 返回确定性测试数据
 *   - "Skip的测试都不合理"：所有用例必须实际执行
 *   - "系统有问题就优化系统"：数据缺失通过 mock 解决，不跳过测试
 */
test.describe('事件列表与详情 @events', () => {
  test.beforeEach(async ({ page }) => {
    await injectLoginState(page)
    await setupMockApi(page)
  })

  test('事件列表页加载，标题与筛选器可见', async ({ page }) => {
    await page.goto('/pages/events/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-events')

    await expect(page.locator('.page-events'), '事件列表页应渲染').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.header-title'), '应显示「事件列表」标题').toContainText('事件列表')

    const filters = ['今天', '本周', '本月', '预定日程', '全部']
    for (const f of filters) {
      await expect(page.locator('.filter-tab', { hasText: f }).first(), `应有筛选「${f}」`).toBeVisible()
    }

    await expect(page.locator('.search-input'), '应有搜索框').toBeVisible()
    await expect(page.locator('.header-action .add-icon, .add-icon').first(), '应有添加按钮').toBeVisible()
  })

  test('日期筛选 tab 可切换', async ({ page }) => {
    await page.goto('/pages/events/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-events')

    const allTab = page.locator('.filter-tab', { hasText: '全部' }).first()
    await allTab.evaluate((el: HTMLElement) => el.click())
    await expect(allTab).toHaveClass(/active/)
    await page.waitForLoadState('networkidle').catch(() => {})
  })

  test('侧边栏可导航到事件列表', async ({ page }) => {
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.pl-sidebar')

    await navigateViaSidebar(page, '事件')
    await expect(page.locator('.page-events'), '侧边栏点击「事件」应到事件列表').toBeVisible({ timeout: 10000 })
  })

  test('点击事件卡片展开内联详情', async ({ page }) => {
    await page.goto('/pages/events/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-events')

    await page.locator('.filter-tab', { hasText: '全部' }).first().evaluate((el: HTMLElement) => el.click())
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const eventCards = page.locator('.event-card')
    await expect(eventCards.first(), 'mock API 应返回事件数据').toBeVisible({ timeout: 10000 })

    await eventCards.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.event-detail, .detail-row').first(), '展开后应显示详情').toBeVisible({ timeout: 5000 })
  })

  test('点击「查看完整详情」跳转事件详情页', async ({ page }) => {
    await page.goto('/pages/events/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-events')

    await page.locator('.filter-tab', { hasText: '全部' }).first().evaluate((el: HTMLElement) => el.click())
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const eventCards = page.locator('.event-card')
    await expect(eventCards.first(), 'mock API 应返回事件数据').toBeVisible({ timeout: 10000 })

    await eventCards.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.event-detail, .detail-row').first()).toBeVisible({ timeout: 5000 })

    const viewDetailBtn = page.locator('.view-detail-btn').first()
    await expect(viewDetailBtn, '展开详情应有「查看完整详情」按钮').toBeAttached({ timeout: 5000 })

    await viewDetailBtn.evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-event-detail'), '应跳转到事件详情页').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.page-event-detail .header-title'), '详情页标题应为「事件详情」').toContainText('事件详情')
  })

  test('事件详情页显示基本信息与分区', async ({ page }) => {
    await page.goto('/pages/events/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-events')

    await page.locator('.filter-tab', { hasText: '全部' }).first().evaluate((el: HTMLElement) => el.click())
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const eventCards = page.locator('.event-card')
    await expect(eventCards.first(), 'mock API 应返回事件数据').toBeVisible({ timeout: 10000 })

    await eventCards.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.event-detail, .detail-row').first()).toBeVisible({ timeout: 5000 })

    const viewDetailBtn = page.locator('.view-detail-btn').first()
    await expect(viewDetailBtn, '应有「查看完整详情」按钮').toBeAttached({ timeout: 5000 })
    await viewDetailBtn.evaluate((el: HTMLElement) => el.click())

    await expect(page.locator('.page-event-detail')).toBeVisible({ timeout: 10000 })
    await expect(page.locator('.back-btn'), '详情页应有返回按钮').toBeVisible()
    await expect(page.locator('.info-card'), '详情页应显示基本信息卡片').toBeVisible()
    const hasSections = await page.locator('.section-card, .empty-associations').count()
    expect(hasSections, '详情页应渲染分区或空状态').toBeGreaterThan(0)
  })

  test('事件详情页返回按钮可返回列表', async ({ page }) => {
    await page.goto('/pages/events/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-events')

    await page.locator('.filter-tab', { hasText: '全部' }).first().evaluate((el: HTMLElement) => el.click())
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const eventCards = page.locator('.event-card')
    await expect(eventCards.first(), 'mock API 应返回事件数据').toBeVisible({ timeout: 10000 })

    await eventCards.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.event-detail, .detail-row').first()).toBeVisible({ timeout: 5000 })

    const viewDetailBtn = page.locator('.view-detail-btn').first()
    await expect(viewDetailBtn, '应有「查看完整详情」按钮').toBeAttached({ timeout: 5000 })
    await viewDetailBtn.evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-event-detail')).toBeVisible({ timeout: 10000 })

    await page.locator('.back-btn').evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-events'), '返回应回到事件列表').toBeVisible({ timeout: 10000 })
  })
})
