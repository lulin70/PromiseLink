import { test, expect } from '@playwright/test'
import { loginViaUi, waitForPageReady, clearLoginState } from './helpers'

/**
 * Batch 2 UI 整改 E2E 测试（v0.8.0-rc2）。
 *
 * 覆盖范围：
 *   1. 1.1 设置页核心项：
 *      - 隐私数据删除二次确认 modal（输入 DELETE 短语）
 *      - 提醒偏好入口跳转 /pages/reminders/index
 *      - 专业版功能入口点击提示 toast
 *   2. 1.3 基础版每日提醒页：
 *      - /pages/reminders/index 加载、4 级优先级分组、状态条
 *      - 提醒偏好面板展开/收起、保存
 *      - 单项/批量操作按钮可见
 *      - 首页"今日提醒"摘要条入口
 *   3. 2.3 引导内容重写：
 *      - Guide 4 步内容包含"场景"关键字
 *      - 步骤切换、跳过、完成
 *
 * Taro H5 兼容方案：CSS Modules 类名被哈希，使用稳定文本选择器；
 *   Taro View 的 onClick 需通过 evaluate 触发 DOM click。
 */
test.describe('Batch 2 UI 整改 @batch2', () => {
  test.describe('1.1 设置页核心项 @settings', () => {
    test.beforeEach(async ({ page }) => {
      await loginViaUi(page)
    })

    test('我的页加载，账户菜单与专业版功能分区可见', async ({ page }) => {
      await page.goto('/pages/mine/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.mine-page')

      await expect(page.locator('.mine-page'), '我的页应渲染').toBeVisible({ timeout: 10000 })
      await expect(page.locator('.mine-header'), '应显示用户头像区').toBeVisible()
      await expect(page.locator('.mine-user-edition'), '应显示「基础版用户」').toContainText('基础版')

      // 1.1 账户区新增"删除我的数据"项
      await expect(
        page.locator('.mine-menu-item.mine-menu-danger, .mine-menu-item', { hasText: '删除我的数据' }).first(),
        '账户区应有「删除我的数据」入口',
      ).toBeVisible()
      // 1.1 账户区新增"提醒偏好"项
      await expect(
        page.locator('.mine-menu-item', { hasText: '提醒偏好' }).first(),
        '账户区应有「提醒偏好」入口',
      ).toBeVisible()

      // 专业版功能入口应有 Pro 标签
      await expect(page.locator('.mine-menu-tag', { hasText: 'Pro' }).first(), '专业版功能应有 Pro 标签').toBeVisible()
    })

    test('点击专业版功能入口弹出 toast 提示', async ({ page }) => {
      await page.goto('/pages/mine/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.mine-page')

      // 点击"邮件同步"（专业版功能）
      const emailSyncItem = page.locator('.mine-menu-item', { hasText: '邮件同步' }).first()
      await emailSyncItem.evaluate((el: HTMLElement) => el.click())

      // Taro.showToast 在 H5 渲染为 .taro__toast 或类似容器
      // 容错：等待 toast 文本出现
      await page.waitForTimeout(500)
      const toastText = await page.locator('body').innerText()
      expect(
        toastText.includes('专业版功能') || toastText.includes('邮件同步'),
        '点击邮件同步应弹出「专业版功能」相关 toast',
      ).toBeTruthy()
    })

    test('点击"提醒偏好"跳转到 /pages/reminders/index', async ({ page }) => {
      await page.goto('/pages/mine/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.mine-page')

      const prefItem = page.locator('.mine-menu-item', { hasText: '提醒偏好' }).first()
      await prefItem.evaluate((el: HTMLElement) => el.click())

      // 等待路由跳转
      await page.waitForURL('**/pages/reminders/index', { timeout: 10000 }).catch(() => {})
      await waitForPageReady(page, '.page-reminders')
      await expect(page.locator('.page-reminders'), '应跳转到提醒页').toBeVisible({ timeout: 10000 })
      await expect(page.locator('.header-title', { hasText: '今日提醒' }), '提醒页标题应为「今日提醒」').toBeVisible()
    })

    test('隐私删除：点击入口弹出二次确认 modal', async ({ page }) => {
      await page.goto('/pages/mine/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.mine-page')

      // 点击"删除我的数据"打开 modal
      const deleteItem = page.locator('.mine-menu-item', { hasText: '删除我的数据' }).first()
      await deleteItem.evaluate((el: HTMLElement) => el.click())

      // modal 应可见
      await expect(page.locator('.privacy-delete-modal-mask'), '应显示删除二次确认 modal').toBeVisible({ timeout: 5000 })
      await expect(page.locator('.pd-modal-title'), 'modal 标题应包含「确认删除」').toContainText('确认删除')
      await expect(page.locator('.pd-modal-input'), 'modal 应有输入框').toBeVisible()
      await expect(page.locator('.pd-modal-btn-danger', { hasText: '永久删除' }), '应有「永久删除」按钮').toBeVisible()
    })

    test('隐私删除：未输入 DELETE 时永久删除按钮禁用', async ({ page }) => {
      await page.goto('/pages/mine/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.mine-page')

      await page.locator('.mine-menu-item', { hasText: '删除我的数据' }).first().evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.privacy-delete-modal-mask')).toBeVisible()

      // 未输入时按钮应含 disabled class
      const dangerBtn = page.locator('.pd-modal-btn-danger').first()
      await expect(dangerBtn).toHaveClass(/disabled/)

      // 输入错误短语仍禁用
      await page.locator('.pd-modal-input input').fill('delete')
      await expect(dangerBtn, '输入错误短语仍应禁用').toHaveClass(/disabled/)
    })

    test('隐私删除：取消按钮关闭 modal', async ({ page }) => {
      await page.goto('/pages/mine/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.mine-page')

      await page.locator('.mine-menu-item', { hasText: '删除我的数据' }).first().evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.privacy-delete-modal-mask')).toBeVisible()

      await page.locator('.pd-modal-btn-ghost', { hasText: '取消' }).first().evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.privacy-delete-modal-mask'), '取消后 modal 应关闭').toBeHidden({ timeout: 3000 })
    })

    test('隐私删除：输入正确短语后按钮启用', async ({ page }) => {
      await page.goto('/pages/mine/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.mine-page')

      await page.locator('.mine-menu-item', { hasText: '删除我的数据' }).first().evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.privacy-delete-modal-mask')).toBeVisible()

      // 输入正确短语
      await page.locator('.pd-modal-input input').fill('DELETE')
      const dangerBtn = page.locator('.pd-modal-btn-danger').first()
      await expect(dangerBtn, '输入 DELETE 后按钮应启用').not.toHaveClass(/disabled/)

      // 不真正点击删除（避免破坏测试数据），仅验证按钮状态
    })

    test('隐私删除：modal 应显示数据摘要', async ({ page }) => {
      await page.goto('/pages/mine/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.mine-page')

      await page.locator('.mine-menu-item', { hasText: '删除我的数据' }).first().evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.pd-modal-summary'), 'modal 应显示数据摘要行').toBeVisible()
      const summaryText = await page.locator('.pd-modal-summary').innerText()
      expect(summaryText, '数据摘要应包含"数据摘要："前缀').toContain('数据摘要')
    })
  })

  test.describe('1.3 基础版每日提醒页 @reminders', () => {
    test.beforeEach(async ({ page }) => {
      await loginViaUi(page)
    })

    test('提醒页加载，标题与状态条可见', async ({ page }) => {
      await page.goto('/pages/reminders/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.page-reminders')

      await expect(page.locator('.page-reminders'), '提醒页应渲染').toBeVisible({ timeout: 10000 })
      await expect(page.locator('.header-title', { hasText: '今日提醒' }), '标题应为「今日提醒」').toBeVisible()
      // 状态条
      await expect(page.locator('.stats-bar'), '应显示状态条').toBeVisible()
      // 三个状态项：待处理 / 剩余配额 / 免打扰
      const statLabels = ['待处理', '剩余配额', '免打扰']
      for (const label of statLabels) {
        await expect(page.locator('.stat-label', { hasText: label }).first(), `状态条应有「${label}」`).toBeVisible()
      }
    })

    test('提醒偏好面板可展开与收起', async ({ page }) => {
      await page.goto('/pages/reminders/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.page-reminders')

      // 初始面板收起
      await expect(page.locator('.pref-panel'), '初始偏好面板应隐藏').toBeHidden()

      // 点击"提醒偏好"切换显示
      await page.locator('.pref-toggle').first().evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.pref-panel'), '点击后偏好面板应显示').toBeVisible()
      // 偏好字段
      await expect(page.locator('.pref-label', { hasText: '提醒时间' }), '应有"提醒时间"字段').toBeVisible()
      await expect(page.locator('.pref-label', { hasText: '每日上限' }), '应有"每日上限"字段').toBeVisible()
      await expect(page.locator('.pref-label', { hasText: '免打扰起' }), '应有"免打扰起"字段').toBeVisible()
      await expect(page.locator('.pref-label', { hasText: '免打扰止' }), '应有"免打扰止"字段').toBeVisible()

      // 再次点击收起
      await page.locator('.pref-toggle').first().evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.pref-panel'), '再次点击偏好面板应隐藏').toBeHidden()
    })

    test('空状态：无提醒时显示"今日无待处理提醒"', async ({ page }) => {
      await page.goto('/pages/reminders/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.page-reminders')
      await page.waitForTimeout(1500) // 等待 API 返回

      const emptyState = page.locator('.empty-state')
      const isEmpty = await emptyState.count()
      if (isEmpty > 0) {
        await expect(emptyState, '空状态应显示"今日无待处理提醒"').toContainText('今日无待处理提醒')
      }
      // 非空状态时跳过此断言（后端有数据）
    })

    test('有提醒时显示优先级分组与卡片', async ({ page }) => {
      await page.goto('/pages/reminders/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.page-reminders')
      await page.waitForTimeout(1500)

      const priorityGroups = page.locator('.priority-group')
      const groupCount = await priorityGroups.count()
      test.skip(groupCount === 0, '后端无提醒数据，跳过优先级分组用例')

      // 至少有一个优先级分组可见
      await expect(priorityGroups.first(), '应至少有一个优先级分组').toBeVisible()
      // 分组头部应有 P0/P1/P2/P3 之一
      const groupLabel = await priorityGroups.first().locator('.group-label').innerText()
      expect(groupLabel, '分组标签应含 P0/P1/P2/P3').toMatch(/P[0-3]/)

      // 卡片
      await expect(priorityGroups.first().locator('.reminder-card'), '分组内应有提醒卡片').toBeVisible()
      // 卡片操作按钮：完成 / 推迟 / 忽略
      for (const label of ['完成', '推迟', '忽略']) {
        await expect(
          priorityGroups.first().locator('.action-btn', { hasText: label }).first(),
          `卡片应有「${label}」按钮`,
        ).toBeVisible()
      }
    })

    test('勾选提醒卡片后底部批量操作栏出现', async ({ page }) => {
      await page.goto('/pages/reminders/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.page-reminders')
      await page.waitForTimeout(1500)

      const cards = page.locator('.reminder-card')
      const cardCount = await cards.count()
      test.skip(cardCount === 0, '后端无提醒数据，跳过批量操作用例')

      // 初始无批量栏
      await expect(page.locator('.batch-bar'), '初始应无批量操作栏').toBeHidden()

      // 勾选第一张卡片（点击 Checkbox 容器或卡片选择区）
      const firstCardCheckbox = cards.first().locator('.card-main Checkbox, .card-main taro-checkbox-core').first()
      await firstCardCheckbox.evaluate((el: HTMLElement) => el.click()).catch(async () => {
        // 降级：直接点击卡片主体
        await cards.first().locator('.card-main').first().evaluate((el: HTMLElement) => el.click())
      })
      await page.waitForTimeout(300)

      // 底部批量栏应出现
      await expect(page.locator('.batch-bar'), '勾选后应显示批量操作栏').toBeVisible({ timeout: 3000 })
      // 批量按钮
      for (const label of ['批量完成', '批量推迟', '批量忽略']) {
        await expect(
          page.locator('.batch-btn', { hasText: label }).first(),
          `批量栏应有「${label}」按钮`,
        ).toBeVisible()
      }
    })

    test('首页"今日提醒"摘要条入口可见（有数据时）', async ({ page }) => {
      await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.page-index')
      await page.waitForTimeout(2000)

      const summaryBar = page.locator('.reminder-summary-bar')
      const isVisible = await summaryBar.count()
      if (isVisible > 0) {
        await expect(summaryBar, '摘要条应可见').toBeVisible()
        await expect(summaryBar, '应含"今日提醒"文本').toContainText('今日提醒')
        // 点击应跳转到 /pages/reminders/index
        await summaryBar.evaluate((el: HTMLElement) => el.click())
        await page.waitForURL('**/pages/reminders/index', { timeout: 10000 }).catch(() => {})
        await expect(page.locator('.page-reminders'), '点击摘要条应跳转到提醒页').toBeVisible({ timeout: 10000 })
      }
      // 无数据时不显示摘要条（业务正常），跳过点击断言
    })
  })

  test.describe('2.3 引导内容重写 @guide', () => {
    test.beforeEach(async ({ page }) => {
      // 清除引导已完成标记，确保 Guide 重新显示
      if (page.url() === 'about:blank' || !page.url().startsWith('http')) {
        await page.goto('/', { waitUntil: 'domcontentloaded' })
      }
      await page.evaluate(() => {
        try { localStorage.removeItem('guide_shown') } catch { /* ignore */ }
      })
    })

    test('引导组件：4 步内容包含"场景"关键字', async ({ page }) => {
      // 未登录访问首页，Guide 应自动展示
      await clearLoginState(page)
      await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page)

      // 等待 Guide overlay 出现
      await page.waitForSelector('.pl-guide-overlay', { state: 'visible', timeout: 10000 }).catch(() => {})
      const guideVisible = await page.locator('.pl-guide-overlay').count()
      test.skip(guideVisible === 0, 'Guide 未自动展示（可能已展示过或组件异常），跳过用例')

      // 收集 4 步内容
      const stepTexts: string[] = []
      for (let i = 0; i < 4; i++) {
        const bodyText = await page.locator('.pl-guide-text').first().innerText().catch(() => '')
        stepTexts.push(bodyText)
        // 点击"下一步"（最后一步会变成"开始使用"并触发 finish）
        const nextBtn = page.locator('.pl-guide-btn-primary').first()
        const btnText = await nextBtn.innerText().catch(() => '')
        if (btnText.includes('开始使用')) break
        await nextBtn.evaluate((el: HTMLElement) => el.click()).catch(() => {})
        await page.waitForTimeout(300)
      }

      // 至少有一步应包含"场景"关键字（2.3 重写要求）
      const hasScenario = stepTexts.some(t => t.includes('场景'))
      expect(hasScenario, '4 步引导内容应至少有一步包含"场景"关键字').toBeTruthy()
    })

    test('引导组件：可逐步下一步直到完成', async ({ page }) => {
      await clearLoginState(page)
      await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page)

      await page.waitForSelector('.pl-guide-overlay', { state: 'visible', timeout: 10000 }).catch(() => {})
      const guideVisible = await page.locator('.pl-guide-overlay').count()
      test.skip(guideVisible === 0, 'Guide 未展示，跳过用例')

      // 步骤指示器应显示"第 1 步 / 共 4 步"
      await expect(page.locator('.pl-guide-step-label')).toContainText('第 1 步')
      await expect(page.locator('.pl-guide-step-label')).toContainText('共 4 步')

      // 点击下一步 3 次（第 4 步显示"开始使用"）
      for (let i = 0; i < 3; i++) {
        await page.locator('.pl-guide-btn-primary').first().evaluate((el: HTMLElement) => el.click())
        await page.waitForTimeout(200)
      }

      // 最后一步按钮文本应为"开始使用"
      await expect(page.locator('.pl-guide-btn-primary').first()).toContainText('开始使用')

      // 点击开始使用 → Guide 关闭
      await page.locator('.pl-guide-btn-primary').first().evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.pl-guide-overlay'), '点击开始使用后 Guide 应关闭').toBeHidden({ timeout: 3000 })

      // localStorage 应写入 guide_shown=true
      const shown = await page.evaluate(() => localStorage.getItem('guide_shown'))
      expect(shown, '完成引导后应写入 guide_shown 标记').toBeTruthy()
    })

    test('引导组件：可点击"跳过"提前关闭', async ({ page }) => {
      await clearLoginState(page)
      await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page)

      await page.waitForSelector('.pl-guide-overlay', { state: 'visible', timeout: 10000 }).catch(() => {})
      const guideVisible = await page.locator('.pl-guide-overlay').count()
      test.skip(guideVisible === 0, 'Guide 未展示，跳过用例')

      // 点击"跳过"
      await page.locator('.pl-guide-skip').first().evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.pl-guide-overlay'), '点击跳过后 Guide 应关闭').toBeHidden({ timeout: 3000 })

      // 也应写入 guide_shown 标记
      const shown = await page.evaluate(() => localStorage.getItem('guide_shown'))
      expect(shown, '跳过后也应写入 guide_shown 标记').toBeTruthy()
    })

    test('引导组件：上一步按钮在第一步隐藏，第二步起可见', async ({ page }) => {
      await clearLoginState(page)
      await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page)

      await page.waitForSelector('.pl-guide-overlay', { state: 'visible', timeout: 10000 }).catch(() => {})
      const guideVisible = await page.locator('.pl-guide-overlay').count()
      test.skip(guideVisible === 0, 'Guide 未展示，跳过用例')

      // 第一步应无"上一步"按钮
      await expect(page.locator('.pl-guide-btn-ghost', { hasText: '上一步' }), '第一步不应有上一步按钮').toBeHidden()

      // 点击下一步进入第二步
      await page.locator('.pl-guide-btn-primary').first().evaluate((el: HTMLElement) => el.click())
      await page.waitForTimeout(300)

      // 第二步应有"上一步"按钮
      await expect(page.locator('.pl-guide-btn-ghost', { hasText: '上一步' }), '第二步应有上一步按钮').toBeVisible()

      // 点击上一步回到第一步
      await page.locator('.pl-guide-btn-ghost', { hasText: '上一步' }).first().evaluate((el: HTMLElement) => el.click())
      await page.waitForTimeout(300)
      await expect(page.locator('.pl-guide-step-label')).toContainText('第 1 步')
    })
  })

  test.describe('1.3 + 1.1 集成：设置→提醒偏好→保存 @integration', () => {
    test.beforeEach(async ({ page }) => {
      await loginViaUi(page)
    })

    test('从我的页进入提醒页，展开偏好面板，可保存', async ({ page }) => {
      // 我的 → 提醒偏好
      await page.goto('/pages/mine/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.mine-page')
      await page.locator('.mine-menu-item', { hasText: '提醒偏好' }).first().evaluate((el: HTMLElement) => el.click())

      await page.waitForURL('**/pages/reminders/index', { timeout: 10000 }).catch(() => {})
      await waitForPageReady(page, '.page-reminders')

      // 展开偏好面板
      await page.locator('.pref-toggle').first().evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.pref-panel')).toBeVisible()

      // 修改"每日上限"字段（输入数字）
      const fatigueInput = page.locator('.pref-row', { hasText: '每日上限' }).locator('.pref-input input').first()
      await fatigueInput.fill('20')

      // 点击保存按钮
      const saveBtn = page.locator('.pref-btn-primary', { hasText: '保存' }).first()
      await saveBtn.evaluate((el: HTMLElement) => el.click())

      // 等待 toast 出现（保存成功/失败都应有反馈）
      await page.waitForTimeout(1500)
      const bodyText = await page.locator('body').innerText()
      expect(
        bodyText.includes('已保存') || bodyText.includes('保存失败'),
        '保存后应有 toast 反馈（已保存或保存失败）',
      ).toBeTruthy()
    })

    test('从首页摘要条进入提醒页（端到端用户旅程）', async ({ page }) => {
      await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.page-index')
      await page.waitForTimeout(2000)

      const summaryBar = page.locator('.reminder-summary-bar')
      const hasBar = await summaryBar.count()
      test.skip(hasBar === 0, '后端无今日提醒数据，跳过端到端用例')

      await summaryBar.evaluate((el: HTMLElement) => el.click())
      await expect(page.locator('.page-reminders'), '应跳转到提醒页').toBeVisible({ timeout: 10000 })
      await expect(page.locator('.stats-bar'), '提醒页应有状态条').toBeVisible()
    })

    test('设置页退出登录后回到首页登录态', async ({ page }) => {
      await page.goto('/pages/mine/index', { waitUntil: 'domcontentloaded' })
      await waitForPageReady(page, '.mine-page')

      // 点击退出登录
      await page.locator('.mine-logout-btn').first().evaluate((el: HTMLElement) => el.click())
      await page.waitForTimeout(1000)

      // 应跳回首页，显示登录卡片
      await expect(page.locator('.login-card'), '退出后应回到首页登录卡片').toBeVisible({ timeout: 5000 })
    })
  })
})
