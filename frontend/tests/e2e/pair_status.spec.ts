import { test, expect, Page, Route } from '@playwright/test'
import { waitForPageReady } from './helpers'

/**
 * 配对页五态渲染 E2E（② 2026-09-21）。
 *
 * 背景（实机 + nginx 日志取证）：网关的 device pair 状态只有
 * `pending` / `matched`（查不到时 `expired`），**`activated` 从来不是网关
 * 给出的值**；而"许可证被拒"只写进本地中继日志。旧页面在 `matched` 就
 * 停止轮询，于是凭据被拒的用户永远停在「正在激活...」，既看不到原因也
 * 拿不到下一步动作。
 *
 * 本 spec 用 page.route 注入网关答案，锁定三件事：
 *   1. matched 之后**必须继续轮询**（否则 rejected/activated 永远不可见）；
 *   2. rejected 与 expired 的文案与视觉可区分（不能都叫"失败"）；
 *   3. 三种 rejected_kind 给出各自的下一步动作文案，且不回显许可证内容。
 *
 * 反向探针：用例 3 的响应序列是 [matched, rejected]。若有人把
 * `startPolling` 退回"matched 即 clearInterval"，该用例必然失败 —— 不会
 * 静默通过。
 *
 * 注意：pair 页不走 LoginGate，因此本 spec 不需要注入登录态，
 * 也不会打到真实网关（所有 /api/v1/pair/** 请求都被拦截）。
 */

const PAIR_API = '**/api/v1/pair/**'

// 跨域：H5 dev server 在 :3000，本地 API 在 :8000。route.fulfill 仍会经过
// 浏览器的 CORS 检查，故必须显式带上允许头，否则 XHR 被判失败、轮询静默吞掉。
const CORS_HEADERS = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET,POST,OPTIONS',
  'access-control-allow-headers': '*',
  'content-type': 'application/json',
}

const INIT_OK = {
  success: true,
  device_pair_code: '384721',
  qr_content: 'https://www.promiselink.cn/pair?code=384721',
  expires_in: 300,
}

/**
 * 拦截 /pair/** ：init 固定成功；status 按传入序列依次返回，用尽后固定为最后一项。
 */
async function installPairRoutes(page: Page, statusSeq: Record<string, unknown>[]) {
  let callIndex = 0
  await page.route(PAIR_API, async (route: Route, request) => {
    if (request.method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: CORS_HEADERS, body: '' })
      return
    }
    if (request.url().includes('/pair/init')) {
      await route.fulfill({
        status: 200,
        headers: CORS_HEADERS,
        body: JSON.stringify(INIT_OK),
      })
      return
    }
    const payload = statusSeq[Math.min(callIndex, statusSeq.length - 1)]
    callIndex += 1
    await route.fulfill({
      status: 200,
      headers: CORS_HEADERS,
      body: JSON.stringify(payload),
    })
  })
}

/** 打开配对页并等到配对码渲染完成。 */
async function openPairPage(page: Page) {
  await page.goto('/pages/pair/index', { waitUntil: 'domcontentloaded' })
  await waitForPageReady(page, '.pair-code')
}

test.describe('配对页五态渲染 @pair', () => {
  test('pending：显示配对码并提示等待扫码', async ({ page }) => {
    await installPairRoutes(page, [{ success: true, status: 'pending' }])
    await openPairPage(page)

    await expect(page.locator('.pair-code'), '应显示配对码').toContainText('384721')
    await expect(
      page.locator('.pair-status.status-pending'),
      'pending 必须用中性样式，且文案指向"等待扫码"',
    ).toContainText('等待小程序扫码配对')
  })

  test('matched → activated：配对码匹配后仍需继续轮询到激活成功', async ({ page }) => {
    await installPairRoutes(page, [
      { success: true, status: 'matched', license_key: 'PL-PRO-TEST-ABCD-EFGH' },
      { success: true, status: 'activated' },
    ])
    await openPairPage(page)

    await expect(
      page.locator('.pair-status.status-success'),
      'activated 必须由本地中继状态合成（网关侧永远给不出这个值）',
    ).toContainText('激活成功', { timeout: 20000 })
    await expect(page.locator('.pair-success-hint'), '激活成功应给出可用性提示').toBeVisible()
  })

  test('matched → rejected(occupied)：matched 后必须继续轮询才能看到被拒原因', async ({
    page,
  }) => {
    // 反向探针：序列第一项是 matched。若轮询在 matched 处停止，本用例拿不到
    // rejected，必然失败。
    await installPairRoutes(page, [
      { success: true, status: 'matched' },
      { success: true, status: 'rejected', rejected_kind: 'occupied' },
    ])
    await openPairPage(page)

    const rejectedBox = page.locator('.pair-status.status-rejected')
    await expect(rejectedBox, '被拒终态必须渲染（不能停在"正在激活..."）').toContainText(
      '许可证未能激活',
      { timeout: 20000 },
    )
    await expect(
      page.locator('.pair-rejected-hint'),
      'occupied 应给出"已绑定其他账号/设备"的下一步动作',
    ).toContainText('已绑定到其他账号或设备')
  })

  test('rejected(not_found)：文案指向"许可证不存在"而非泛泛失败', async ({ page }) => {
    await installPairRoutes(page, [
      { success: true, status: 'matched' },
      { success: true, status: 'rejected', rejected_kind: 'not_found' },
    ])
    await openPairPage(page)

    await expect(page.locator('.pair-status.status-rejected')).toContainText('许可证未能激活', {
      timeout: 20000,
    })
    await expect(page.locator('.pair-rejected-hint')).toContainText('网关没有找到这把许可证')
  })

  test('rejected(invalid)：文案指向"许可证已过期/停用/退还"', async ({ page }) => {
    await installPairRoutes(page, [
      { success: true, status: 'matched' },
      { success: true, status: 'rejected', rejected_kind: 'invalid' },
    ])
    await openPairPage(page)

    await expect(page.locator('.pair-status.status-rejected')).toContainText('许可证未能激活', {
      timeout: 20000,
    })
    await expect(page.locator('.pair-rejected-hint')).toContainText('当前不可用')
  })

  test('expired：配对码到期与许可证被拒必须是两套文案/两套样式', async ({ page }) => {
    await installPairRoutes(page, [{ success: true, status: 'expired' }])
    await openPairPage(page)

    const expiredBox = page.locator('.pair-status.status-expired')
    await expect(expiredBox, 'expired 应有独立样式（status-expired）').toContainText(
      '配对码已过期',
      { timeout: 20000 },
    )
    // 反向探针：到期不是"许可证问题"，不得出现被拒引导块
    await expect(page.locator('.pair-rejected-hint')).toHaveCount(0)
    await expect(expiredBox).not.toHaveClass(/status-rejected/)
  })

  test('rejected 页不回显任何许可证内容', async ({ page }) => {
    await installPairRoutes(page, [
      {
        success: true,
        status: 'rejected',
        rejected_kind: 'occupied',
        license_key: 'PL-PRO-LEAK-CHECK-0001',
      },
    ])
    await openPairPage(page)

    await expect(page.locator('.pair-status.status-rejected')).toContainText('许可证未能激活', {
      timeout: 20000,
    })
    await expect(
      page.locator('body'),
      '被拒页面不得把 license_key 回显到用户界面',
    ).not.toContainText('PL-PRO-LEAK-CHECK-0001')
  })
})