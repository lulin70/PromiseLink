import { test, expect } from '@playwright/test'
import { loginViaUi, navigateViaSidebar, waitForPageReady } from './helpers'

/**
 * 事件录入测试：录入页可访问、文本输入框可用、提交事件、文件上传可见。
 *
 * 录入页（src/pages/input/index.tsx）结构：
 *   - 顶部 tab：事件录入 / 需求
 *   - 事件类型选择（手动录入/会议/电话/微信转发）
 *   - 输入模式切换：文本输入 / 文件上传
 *   - 文本模式：textarea + 参与者 + 时间 + 「记录并解析」按钮
 *   - 文件模式：.txt/.md 文件选择区
 *
 * 前置：需登录；提交事件需后端运行（POST /api/v1/events）。
 */
test.describe('事件录入 @input', () => {
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page)
  })

  test('录入页面可访问，标题与表单可见', async ({ page }) => {
    // 通过首页 FAB 按钮或侧边栏导航到录入页（模拟真实用户路径）
    await page.goto('/pages/input/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-input')

    await expect(page.locator('.page-input'), '录入页应渲染').toBeVisible({ timeout: 10000 })
    await expect(page.locator('.header-title'), '录入页应显示标题').toContainText('事件录入')
  })

  test('事件录入 tab 与需求 tab 可切换', async ({ page }) => {
    await page.goto('/pages/input/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-input')

    // 默认「事件录入」tab 激活
    const eventTab = page.locator('.input-tab', { hasText: '事件录入' })
    await expect(eventTab).toBeVisible()

    // 切换到「需求」tab
    await page.locator('.input-tab', { hasText: '需求' }).evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.text-input').first(), '需求 tab 应显示需求输入框').toBeVisible({ timeout: 5000 })
  })

  test('文本输入框可用并可输入', async ({ page }) => {
    await page.goto('/pages/input/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-input')

    // 确保在事件录入 tab
    await page.locator('.input-tab', { hasText: '事件录入' }).evaluate((el: HTMLElement) => el.click())

    // 文本模式下的 textarea（Taro 渲染为 <taro-textarea-core>，需定位内部 <textarea>）
    const textarea = page.locator('.text-input textarea').first()
    await expect(page.locator('.text-input').first(), '应有文本输入框').toBeVisible({ timeout: 5000 })

    // 模拟用户输入
    await textarea.fill('今天和张总开会讨论了合作方案，他答应下周三前给反馈。')
    await expect(textarea).toHaveValue(/张总/)
  })

  test('事件类型选择器可见且可切换', async ({ page }) => {
    await page.goto('/pages/input/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-input')

    await page.locator('.input-tab', { hasText: '事件录入' }).evaluate((el: HTMLElement) => el.click())

    // 事件类型按钮：手动录入/会议/电话/微信转发
    const typeGrid = page.locator('.event-type-grid')
    await expect(typeGrid, '应有事件类型选择区').toBeVisible({ timeout: 5000 })
    await expect(page.locator('.event-type-btn', { hasText: '会议' })).toBeVisible()
    await expect(page.locator('.event-type-btn', { hasText: '电话' })).toBeVisible()

    // 点击「会议」应激活
    await page.locator('.event-type-btn', { hasText: '会议' }).evaluate((el: HTMLElement) => el.click())
    await expect(page.locator('.event-type-btn', { hasText: '会议' })).toHaveClass(/active/)
  })

  test('文件上传模式可见，支持 .txt/.md', async ({ page }) => {
    await page.goto('/pages/input/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-input')

    await page.locator('.input-tab', { hasText: '事件录入' }).evaluate((el: HTMLElement) => el.click())

    // 切换到文件上传模式
    await page.locator('.mode-btn', { hasText: '文件上传' }).evaluate((el: HTMLElement) => el.click())

    // 文件上传区可见
    await expect(page.locator('.file-upload-area'), '文件上传区应可见').toBeVisible({ timeout: 5000 })
    // 提示文案表明支持 .txt/.md
    const uploadAreaText = await page.locator('.file-upload-area').innerText()
    expect(uploadAreaText, '应提示支持 .txt/.md 格式').toMatch(/\.txt.*\.md|\.md.*\.txt/)

    // 原生 file input 应存在且 accept .txt,.md
    const fileInput = page.locator('input[type="file"]')
    await expect(fileInput, '应有原生文件输入').toHaveCount(1)
    const accept = await fileInput.getAttribute('accept')
    expect(accept, '文件输入应 accept .txt,.md').toContain('.txt')
    expect(accept, '文件输入应 accept .txt,.md').toContain('.md')
  })

  test('提交事件后进入解析结果视图', async ({ page }) => {
    // 前置：需后端运行。提交事件 → 后端创建 → 进入 result 视图
    await page.goto('/pages/input/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-input')

    await page.locator('.input-tab', { hasText: '事件录入' }).evaluate((el: HTMLElement) => el.click())

    // 输入内容
    await page.locator('.text-input textarea').first().fill('测试事件：与李总电话沟通项目进度，需要本周五前提交方案。')

    // 点击「记录并解析」
    const submitBtn = page.locator('.submit-btn', { hasText: '记录并解析' })
    await expect(submitBtn).toBeVisible()
    await submitBtn.evaluate((el: HTMLElement) => el.click())

    // 提交成功后应进入结果视图（result-card 出现）
    await expect(page.locator('.result-card'), '提交后应进入解析结果视图').toBeVisible({ timeout: 20000 })
    // 结果视图应显示事件标题或处理状态
    await expect(page.locator('.result-header')).toBeVisible()
  })

  test('首页 FAB 按钮可跳转录入页', async ({ page }) => {
    // 回到首页，通过 FAB 按钮进入录入页（真实用户路径）
    await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
    await waitForPageReady(page, '.page-index')

    const fab = page.locator('.fab-btn')
    await expect(fab, '首页应有 FAB 录入按钮').toBeVisible({ timeout: 10000 })
    await fab.evaluate((el: HTMLElement) => el.click())

    // 应跳转到录入页
    await expect(page.locator('.page-input'), '点击 FAB 应跳转录入页').toBeVisible({ timeout: 10000 })
  })
})
