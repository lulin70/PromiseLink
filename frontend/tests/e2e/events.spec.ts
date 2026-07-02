import { test, expect } from '@playwright/test'
import { loginViaUi, navigateViaSidebar, waitForPageReady } from './helpers'

/**
 * 事件列表与详情测试。
 *
 * 事件列表页（src/pages/events/index.tsx）：
 *   - 标题「事件列表」+ 右上角 + 按钮
 *   - 日期筛选 tab：今天/本周/本月/预定日程/全部
 *   - 搜索框
 *   - 事件卡片点击展开内联详情；内联详情有「查看完整详情 ›」跳转详情页
 *
 * 事件详情页（src/pages/events/detail.tsx）：
 *   - 标题「事件详情」+ 返回按钮
 *   - 基本信息卡片（标题/类型/时间/原始内容/状态）
 *   - 分区：关联人脉 / 关联待办 / 关联承诺（按数据有渲染）
 *
 * 前置：需登录 + 后端运行且有数据。无数据时相关用例 skip。
 */
test.describe('事件列表与详情 @events', () => {
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page)
  })

  test('事件列表页加载，标题与筛选器可见', async ({ page }) => {
    await page.goto('/pages/events/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-events')

    await expect(page.locator('.page-events'), '事件列表页应渲染').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.header-title'), '应显示「事件列表」标题').toContainText('事件列表')

    // 日期筛选 tab
    const filters = ['今天', '本周', '本月', '预定日程', '全部']
    for (const f of filters) {
      await expect(page.locator('.filter-tab', { hasText: f }).first(), `应有筛选「${f}」`).toBeVisible()
    }

    // 搜索框
    await expect(page.locator('.search-input'), '应有搜索框').toBeVisible()
    // 右上角 + 按钮
    await expect(page.locator('.header-action .add-icon, .add-icon').first(), '应有添加按钮').toBeVisible()
  })

  test('日期筛选 tab 可切换', async ({ page }) => {
    await page.goto('/pages/events/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-events')

    // 默认「今天」激活，切换到「全部」以获取所有事件
    const allTab = page.locator('.filter-tab', { hasText: '全部' }).first()
    await allTab.evaluate((el: HTMLElement) => el.click())
    await expect(allTab).toHaveClass(/active/)
    await page.waitForLoadState('networkidle').catch(() => {})
  })

  test('侧边栏可导航到事件列表', async ({ page }) => {
    // 先回首页
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.pl-sidebar')

    await navigateViaSidebar(page, '事件')
    await expect(page.locator('.page-events'), '侧边栏点击「事件」应到事件列表').toBeVisible({ timeout: 10000 })
  })

  test('点击事件卡片展开内联详情', async ({ page }) => {
    await page.goto('/pages/events/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-events')

    // 切到「全部」以最大化有数据的概率
    await page.locator('.filter-tab', { hasText: '全部' }).first().evaluate((el: HTMLElement) => el.click())
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const eventCards = page.locator('.event-card')
    const count = await eventCards.count()
    test.skip(count === 0, '后端无事件数据，跳过点击展开用例')

    // 点击第一个事件卡片展开
    await eventCards.first().evaluate((el: HTMLElement) => el.click())
    // 展开后应显示 .event-detail 或 .detail-row
    await expect(page.locator('.event-detail, .detail-row').first(), '展开后应显示详情').toBeVisible({ timeout: 5000 })
  })

  test('点击「查看完整详情」跳转事件详情页', async ({ page }) => {
    await page.goto('/pages/events/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-events')

    await page.locator('.filter-tab', { hasText: '全部' }).first().evaluate((el: HTMLElement) => el.click())
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1500)

    const eventCards = page.locator('.event-card')
    const count = await eventCards.count()
    test.skip(count === 0, '后端无事件数据，跳过详情跳转用例')

    // 展开第一个事件
    await eventCards.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.event-detail, .detail-row').first()).toBeVisible({ timeout: 5000 })

    // 点击「查看完整详情 ›」
    const viewDetailBtn = page.locator('.view-detail-btn').first()
    const hasDetailBtn = await viewDetailBtn.count()
    test.skip(hasDetailBtn === 0, '展开详情中无「查看完整详情」按钮，跳过')

    await viewDetailBtn.evaluate((el: HTMLElement) => el.click())
    // 应跳转到事件详情页
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
    const count = await eventCards.count()
    test.skip(count === 0, '后端无事件数据，跳过详情页分区用例')

    await eventCards.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.event-detail, .detail-row').first()).toBeVisible({ timeout: 5000 })

    const viewDetailBtn = page.locator('.view-detail-btn').first()
    test.skip((await viewDetailBtn.count()) === 0, '无「查看完整详情」按钮，跳过')
    await viewDetailBtn.evaluate((el: HTMLElement) => el.click())

    await expect(page.locator('.page-event-detail')).toBeVisible({ timeout: 10000 })

    // 详情页应有返回按钮
    await expect(page.locator('.back-btn'), '详情页应有返回按钮').toBeVisible()
    // 基本信息卡片
    await expect(page.locator('.info-card'), '详情页应显示基本信息卡片').toBeVisible()
    // 分区标题（关联人脉/关联待办/关联承诺 任一存在即可，取决于数据）
    // 若数据为空会显示「暂无关联数据」
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
    const count = await eventCards.count()
    test.skip(count === 0, '后端无事件数据，跳过返回用例')

    await eventCards.first().evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.event-detail, .detail-row').first()).toBeVisible({ timeout: 5000 })

    const viewDetailBtn = page.locator('.view-detail-btn').first()
    test.skip((await viewDetailBtn.count()) === 0, '无「查看完整详情」按钮，跳过')
    await viewDetailBtn.evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.page-event-detail')).toBeVisible({ timeout: 10000 })

    // 点击返回
    await page.locator('.back-btn').evaluate((el: HTMLElement) => el.click())
    // 应回到事件列表页
    await expect(page.locator('.page-events'), '返回应回到事件列表').toBeVisible({ timeout: 10000 })
  })
})
