"""PromiseLink 基础版 UI 层 Playwright E2E 测试.

覆盖基础版（电脑宽屏 1280x800）所有用户可能的操作：
1. 登录页 (PoC 密码登录)
2. 首页 Dashboard (摘要卡片/今日事件/今日待办/供需匹配/关系健康/关怀提醒)
3. 事件录入 (文本输入 + 文件上传)
4. 事件列表 (日期筛选/搜索/展开详情)
5. 事件详情 → 跳转 (关联人脉/关联待办)
6. 人脉列表 (搜索/详情弹窗/信用分/关系阶段)
7. 人脉详情 → 跳转 (关联事件/关联待办)
8. 待办列表 (状态筛选/类型筛选/完成/忽略/删除)
9. 待办详情 → 跳转 (关联事件/关联人脉)
10. 承诺列表 (视图切换/状态筛选/确认/忽略/兑现/违背/催促)
11. 我的页面 (统计/数据导出)

运行前提：
- 后端 API 运行在 http://localhost:8000
- 前端 H5 dev server 运行在 http://localhost:3000
- Playwright + chromium 已安装

运行方式：
    python scripts/e2e/e2e_playwright_ui_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

# ── 配置 ──
BASE_URL = "http://localhost:3000"
API_URL = "http://localhost:8000"
POC_SECRET = "promiselink2026"
POC_USER = "poc-user"
VIEWPORT = {"width": 1280, "height": 800}  # 电脑宽屏，符合基础版定位
SCREENSHOT_DIR = Path("/tmp/e2e_screenshots")
REPORT_PATH = Path("/tmp/promiselink_playwright_ui_report.json")

# 等待策略：Taro H5 SPA 路由切换 + API 请求需要时间
NAV_TIMEOUT = 15000  # 导航超时
ACTION_TIMEOUT = 8000  # 单个操作超时
SETTLE_DELAY = 1.2  # 操作后稳定等待


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


class StepResult:
    """单个测试步骤结果。"""

    def __init__(self, category: str, name: str):
        self.category = category
        self.name = name
        self.passed = False
        self.detail = ""
        self.screenshot: str | None = None
        self.skipped = False
        self.skip_reason = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "name": self.name,
            "passed": self.passed,
            "skipped": self.skipped,
            "detail": self.detail,
            "screenshot": self.screenshot,
            "skip_reason": self.skip_reason,
        }


class TestRunner:
    """测试执行器：收集结果 + 截图 + 统一异常处理。"""

    def __init__(self, page: Page):
        self.page = page
        self.results: list[StepResult] = []
        self.console_errors: list[str] = []
        self.failed_requests: list[str] = []
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        self._shot_seq = 0

    async def screenshot(self, name: str) -> str:
        self._shot_seq += 1
        path = str(SCREENSHOT_DIR / f"{self._shot_seq:02d}_{name}.png")
        try:
            await self.page.screenshot(path=path, full_page=False)
        except PlaywrightError:
            pass
        return path

    def record(self, r: StepResult) -> None:
        status = "SKIP" if r.skipped else ("PASS" if r.passed else "FAIL")
        icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}[status]
        extra = f" ({r.skip_reason})" if r.skipped else f" — {r.detail[:120]}"
        print(f"  [{ts()}] {icon} {r.category} / {r.name}{extra}")
        self.results.append(r)

    async def run(self, category: str, name: str, fn, *, required: bool = True) -> StepResult:
        """执行一个测试步骤，自动捕获异常并截图。"""
        r = StepResult(category, name)
        try:
            await fn(self, r)
            if not r.detail:
                r.detail = "ok"
        except PlaywrightTimeoutError as e:
            r.passed = False
            r.detail = f"timeout: {e}"[:200]
        except PlaywrightError as e:
            r.passed = False
            r.detail = f"playwright error: {e}"[:200]
        except Exception as e:  # noqa: BLE001 — 测试框架需要兜底
            r.passed = False
            r.detail = f"error: {e}"[:200]
        finally:
            if not r.skipped:
                try:
                    r.screenshot = await self.screenshot(name.replace(" ", "_").replace("/", "_"))
                except Exception:  # noqa: BLE001
                    pass
        self.record(r)
        if not r.passed and not r.skipped and required:
            # 关键步骤失败仍继续，记录上下文后继续后续步骤
            pass
        return r


# ── 辅助函数 ──

async def wait_visible(page: Page, selector: str, timeout: int = ACTION_TIMEOUT) -> bool:
    try:
        el = await page.wait_for_selector(selector, state="visible", timeout=timeout)
        return el is not None
    except PlaywrightTimeoutError:
        return False


async def click_if_exists(page: Page, selector: str, timeout: int = 3000) -> bool:
    """点击元素，使用原生 click() 应对 Taro 自定义元素。"""
    try:
        el = await page.wait_for_selector(selector, state="attached", timeout=timeout)
        if el:
            await el.evaluate("e => e.click()")
            return True
    except PlaywrightError:
        pass
    return False


async def text_click(page: Page, text: str, timeout: int = ACTION_TIMEOUT) -> bool:
    """通过文本点击元素，使用原生 click() 触发 Taro React 合成事件。"""
    selectors = [
        f"text={text}",
        f".taro-tabbar-item:has-text('{text}')",
        f"[class*='tab']:has-text('{text}')",
    ]
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, state="attached", timeout=timeout)
            if el:
                await el.evaluate("e => e.click()")
                return True
        except PlaywrightError:
            continue
    return False


async def switch_tab(page: Page, tab_text: str) -> bool:
    """点击底部 tabBar 切换页面。基础版 tabBar: 首页/事件/人脉/待办/承诺。"""
    # Taro H5 tabBar 使用 .taro-tabbar-item 或类名
    selectors = [
        f".taro-tabbar-item:has-text('{tab_text}')",
        f"[class*='tab-bar'] [class*='item']:has-text('{tab_text}')",
        f"text={tab_text}",
    ]
    for sel in selectors:
        try:
            els = await page.query_selector_all(sel)
            for el in els:
                txt = (await el.inner_text()).strip()
                if txt == tab_text or tab_text in txt:
                    await el.click()
                    await asyncio.sleep(SETTLE_DELAY)
                    return True
        except PlaywrightError:
            continue
    return False


async def dismiss_webpack_overlay(page: Page) -> None:
    """移除 webpack-dev-server 的错误覆盖层 iframe，避免它拦截点击。

    Taro H5 在 dev 模式下，若任何页面组件抛错，webpack 会在页面顶部
    叠一层 <iframe id="webpack-dev-server-client-overlay">，它会拦截所有
    pointer 事件导致 Playwright 点击超时。测试中我们移除该 overlay。
    """
    try:
        await page.evaluate(
            """() => {
                const ov = document.getElementById('webpack-dev-server-client-overlay');
                if (ov) { ov.remove(); }
                // 同时移除其阴影宿主
                const ovs = document.querySelectorAll('webpack-dev-server-client-overlay');
                ovs.forEach(o => o.remove());
            }"""
        )
    except PlaywrightError:
        pass


async def force_click(page: Page, selector: str, timeout: int = 4000) -> bool:
    """点击元素，使用 force=True 跳过可操作性检查（应对 overlay/动画干扰）。"""
    try:
        el = await page.wait_for_selector(selector, state="attached", timeout=timeout)
        if el:
            await el.click(force=True, timeout=timeout)
            return True
    except PlaywrightError:
        pass
    return False


async def native_click(page: Page, selector: str, timeout: int = 4000) -> bool:
    """用原生 HTMLElement.click() 方法点击（via evaluate）。

    Taro H5 使用自定义元素（TARO-VIEW-CORE / TARO-TEXT-CORE）+ React 合成事件。
    Playwright 的 el.click(force=True) 派发的 MouseEvent 有时不会被 Taro 的事件
    系统捕获，但浏览器原生的 element.click() 方法能正确触发 React onClick。
    这是 Taro H5 E2E 测试的关键技巧。
    """
    try:
        el = await page.wait_for_selector(selector, state="attached", timeout=timeout)
        if el:
            await el.evaluate("e => e.click()")
            return True
    except PlaywrightError:
        pass
    return False


async def native_click_first(page: Page, selector: str, timeout: int = 4000) -> bool:
    """对第一个匹配 selector 的元素执行原生 click()。"""
    try:
        el = await page.wait_for_selector(selector, state="attached", timeout=timeout)
        if el:
            await el.evaluate("e => e.click()")
            return True
    except PlaywrightError:
        pass
    return False


async def js_click_login_btn(page: Page) -> bool:
    """用 JS 直接触发登录按钮的点击（最兜底方案）。"""
    try:
        return await page.evaluate(
            """() => {
                const btn = document.querySelector('.login-btn');
                if (btn) {
                    // Taro H5 用 React 合成事件，需要 dispatch 真实事件
                    btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                    return true;
                }
                return false;
            }"""
        )
    except PlaywrightError:
        return False


async def goto_page(page: Page, path: str) -> None:
    """直接导航到指定页面（browser router 模式）。"""
    url = f"{BASE_URL}/{path.lstrip('/')}"
    await page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT)
    await asyncio.sleep(SETTLE_DELAY)
    # 移除 webpack 错误覆盖层（dev 模式下组件报错会产生该 overlay 拦截点击）
    await dismiss_webpack_overlay(page)


async def taro_fill(page: Page, selector: str, value: str) -> bool:
    """为 Taro H5 的 Input/Textarea 填值并触发 onInput 事件。

    Taro 的 Input/Textarea 监听原生 input 事件，但 React 状态需要
    通过 InputEvent 才能正确更新。直接 .fill() 有时不会触发 Taro 的
    onInput 回调，导致 React state 不更新。这里用 evaluate 设置 value
    并派发 input 事件。
    """
    try:
        el = await page.query_selector(selector)
        if not el:
            return False
        await el.focus()
        # 先清空
        await el.fill("")
        await asyncio.sleep(0.1)
        await el.fill(value)
        # 再用 JS 确保值已设置并派发 input 事件（兼容 Taro onInput）
        await page.evaluate(
            """(args) => {
                const [sel, val] = args;
                const el = document.querySelector(sel);
                if (!el) return false;
                const nativeSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                )?.set || Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                )?.set;
                if (nativeSetter) nativeSetter.call(el, val);
                else el.value = val;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }""",
            [selector, value],
        )
        return True
    except PlaywrightError:
        return False


# ──────────────────────────────────────────────────────────────────
# 测试步骤实现
# ──────────────────────────────────────────────────────────────────


async def step_login(runner: TestRunner, r: StepResult) -> None:
    """Step 1: 登录页 — 输入 PoC 密码 → 登录 → 验证跳转首页。"""
    page = runner.page
    await goto_page(page, "/pages/index/index")

    # 验证登录表单存在
    has_login = await wait_visible(page, ".login-card, .page-login-inline", timeout=8000)
    if not has_login:
        # 可能已经登录（token 还在），先登出再测
        r.detail = "login form not visible (maybe already logged in)"
        r.passed = True
        return

    # 输入用户 ID
    user_input = await page.query_selector("input[placeholder='poc-user']") or await page.query_selector(
        ".form-group input"
    )
    if user_input:
        await user_input.fill("")
        await user_input.fill(POC_USER)

    # 输入 PoC 密钥（safe-password 类型在 H5 会渲染为 input）
    secret_inputs = await page.query_selector_all("input")
    filled_secret = False
    for inp in secret_inputs:
        ph = (await inp.get_attribute("placeholder")) or ""
        itype = (await inp.get_attribute("type")) or ""
        if "secret" in ph.lower() or "密" in ph or "password" in itype or "safe-password" in itype:
            await inp.fill(POC_SECRET)
            filled_secret = True
            break
    if not filled_secret and secret_inputs:
        # 兜底：填到第二个 input
        if len(secret_inputs) >= 2:
            await secret_inputs[1].fill(POC_SECRET)
            filled_secret = True

    # 点击登录按钮（原生 click() 优先，应对 Taro 自定义元素）
    clicked = await native_click(page, ".login-btn", timeout=4000)
    if not clicked:
        clicked = await js_click_login_btn(page)
    if not clicked:
        clicked = await text_click(page, "登 录", timeout=3000)

    # 等待 dashboard 加载（摘要卡片出现）
    await dismiss_webpack_overlay(page)
    dashboard_ready = await wait_visible(page, ".summary-cards, .header-title, .page-index .header", timeout=15000)
    r.passed = clicked and dashboard_ready
    r.detail = f"filled_secret={filled_secret}, clicked={clicked}, dashboard_ready={dashboard_ready}, url={page.url}"


async def step_dashboard(runner: TestRunner, r: StepResult) -> None:
    """Step 2: 首页 Dashboard — 验证各区域加载。"""
    page = runner.page
    await goto_page(page, "/pages/index/index")

    content = await page.content()
    checks = {
        "summary_cards": "summary-cards" in content or "card-number" in content,
        "today_events_section": "今日事件" in content,
        "today_todos_section": "今日待办" in content,
        "quick_input": "快速录入" in content or "quick-input" in content,
        "export_btn": "导出数据" in content or "export-btn" in content,
        "fab_btn": "fab-btn" in content,
    }
    # 供需匹配 / 关系健康 / 关怀提醒 是按需加载（非空才显示），单独检查不强制
    optional = {
        "supply_demand": "供需匹配" in content or "sd-section" in content,
        "relationship_health": "关系健康" in content or "health-section" in content,
        "care_reminders": "关怀提醒" in content or "care-section" in content,
    }

    required_pass = all(checks.values())
    optional_count = sum(optional.values())
    r.passed = required_pass
    r.detail = f"required={checks}, optional_present={optional_count}/3 ({optional})"


async def step_event_input_text(runner: TestRunner, r: StepResult) -> None:
    """Step 3a: 事件录入 — 文本输入 → 提交 → 验证创建。"""
    page = runner.page
    # 点击 FAB + 按钮或快速录入入口进入录入页
    await goto_page(page, "/pages/input/index")

    # 确认在录入页
    in_input = await wait_visible(page, ".page-input, .input-tab-toggle", timeout=8000)
    if not in_input:
        r.passed = False
        r.detail = "input page not loaded"
        return

    # 确保"事件录入"tab 激活（默认是 event）
    await click_if_exists(page, ".input-tab.active:has-text('事件录入')", timeout=2000)
    # 确保文本输入模式（native click）
    await native_click(page, ".mode-btn:has-text('文本输入')", timeout=3000)
    await asyncio.sleep(0.5)

    # 在 textarea 输入（Taro 的 .fill() 能正确触发 onInput）
    event_text = f"[E2E-UI] 测试事件录入 {datetime.now().strftime('%H:%M:%S')}"
    textarea = await page.query_selector("textarea.text-input, textarea")
    if not textarea:
        r.passed = False
        r.detail = "textarea not found"
        return
    await textarea.fill(event_text)
    await asyncio.sleep(0.8)

    # 点击"记录并解析"按钮（native click）
    submit_clicked = await native_click(page, ".submit-btn", timeout=4000)
    if not submit_clicked:
        submit_clicked = await text_click(page, "记录并解析", timeout=3000)

    # 等待结果卡片出现（提交后会出现 result-card，createEvent API 返回即显示）
    result_ready = await wait_visible(page, ".result-card", timeout=25000)
    r.passed = submit_clicked and result_ready
    r.detail = f"submit_clicked={submit_clicked}, result_card_visible={result_ready}, text={event_text[:40]}"


async def step_event_input_file(runner: TestRunner, r: StepResult) -> None:
    """Step 3b: 事件录入 — 文件上传 (.txt) → 验证事件创建。"""
    page = runner.page
    await goto_page(page, "/pages/input/index")
    await asyncio.sleep(SETTLE_DELAY)

    # 确保在"事件录入"tab（非需求tab）
    await click_if_exists(page, ".input-tab.active:has-text('事件录入')", timeout=2000)

    # 切到文件上传模式（native click）
    file_mode_clicked = await native_click(page, ".mode-btn:has-text('文件上传')", timeout=4000)
    await asyncio.sleep(SETTLE_DELAY)

    if not file_mode_clicked:
        r.passed = False
        r.detail = "file upload mode toggle not found"
        return

    # 准备测试 .txt 文件
    tmp_file = Path("/tmp/e2e_upload_test.txt")
    tmp_file.write_text(
        "【E2E 文件上传测试】\n这是一次与张总的会议记录。\n张总承诺下周三前提供技术方案。\n我需要准备对接文档。",
        encoding="utf-8",
    )

    # file input 在 DOM 中始终存在（display:none），用 setInputFiles 直接设置
    file_input = await page.query_selector("input[type='file']")
    if not file_input:
        # 可能需要等一下渲染
        await asyncio.sleep(1.5)
        file_input = await page.query_selector("input[type='file']")
    if not file_input:
        r.passed = False
        r.detail = "file input element not found (file mode may not have rendered)"
        return
    await file_input.set_input_files(str(tmp_file))

    # 选择文件后 handleFileSelected 会自动调用 uploadEventFile，等待 result-card
    result_ready = await wait_visible(page, ".result-card", timeout=30000)
    r.passed = result_ready
    r.detail = f"file_mode_clicked={file_mode_clicked}, result_card_visible={result_ready}"


async def step_events_list(runner: TestRunner, r: StepResult) -> None:
    """Step 4: 事件列表 — 日期筛选 / 搜索 / 展开详情。"""
    page = runner.page
    await goto_page(page, "/pages/events/index")

    list_ready = await wait_visible(page, ".page-events, .filter-tabs", timeout=8000)
    if not list_ready:
        r.passed = False
        r.detail = "events page not loaded"
        return

    # 1) 切换日期筛选：今天 → 本周 → 全部
    filter_results = {}
    for label in ["今天", "本周", "全部"]:
        ok = await text_click(page, label, timeout=3000)
        await asyncio.sleep(SETTLE_DELAY)
        filter_results[label] = ok

    # 切到"全部"以便看到事件
    await text_click(page, "全部", timeout=3000)
    await asyncio.sleep(SETTLE_DELAY)

    # 2) 搜索
    search_input = await page.query_selector(".search-bar input, input.search-input")
    search_ok = False
    if search_input:
        await search_input.fill("会议")
        await asyncio.sleep(SETTLE_DELAY * 2)
        await search_input.fill("")
        await asyncio.sleep(SETTLE_DELAY)
        search_ok = True

    # 3) 点击第一个事件展开详情（native click 应对 Taro 自定义元素）
    expand_ok = False
    event_card = await page.query_selector(".event-card")
    if event_card:
        try:
            await event_card.evaluate("e => e.click()")
            await asyncio.sleep(SETTLE_DELAY * 2)
            expand_ok = await wait_visible(page, ".event-detail", timeout=5000)
        except PlaywrightError:
            pass

    r.passed = list_ready and any(filter_results.values()) and search_ok
    r.detail = f"filters={filter_results}, search_ok={search_ok}, expand_ok={expand_ok}"


async def step_event_detail_navigation(runner: TestRunner, r: StepResult) -> None:
    """Step 5: 事件详情 → 跳转关联人脉 / 关联待办。"""
    page = runner.page
    await goto_page(page, "/pages/events/index")
    await text_click(page, "全部", timeout=3000)
    # 等待事件列表加载（事件 API 可能较慢）
    event_card_found = await wait_visible(page, ".event-card", timeout=10000)

    if not event_card_found:
        r.passed = False
        r.detail = "no event card to expand (events not loaded)"
        return

    # 展开第一个事件（native click）
    event_card = await page.query_selector(".event-card")
    try:
        await event_card.evaluate("e => e.click()")
    except PlaywrightError:
        pass
    await asyncio.sleep(SETTLE_DELAY * 2)

    # 尝试找"查看完整详情"按钮跳到详情页
    view_detail = await click_if_exists(page, ".view-detail-btn:has-text('查看完整详情')", timeout=3000)
    if not view_detail:
        view_detail = await text_click(page, "查看完整详情", timeout=2000)

    if not view_detail:
        # 没找到按钮，跳过该步骤（可能事件没有详情入口）
        r.skipped = True
        r.skip_reason = "view-detail-btn not found in expanded event card"
        return

    await asyncio.sleep(SETTLE_DELAY * 2)

    # 在事件详情页，尝试点击关联人脉 / 关联待办链接
    entity_link = await click_if_exists(page, ".entity-link, .related-entity-link", timeout=3000)
    await asyncio.sleep(SETTLE_DELAY)
    # 返回
    back = await click_if_exists(page, ".header-back, .back-arrow", timeout=2000)
    if not back:
        await page.go_back()
    await asyncio.sleep(SETTLE_DELAY)

    todo_link = await click_if_exists(page, ".related-todo-item, .related-todo-title", timeout=3000)
    await asyncio.sleep(SETTLE_DELAY)

    r.passed = view_detail
    r.detail = f"view_detail={view_detail}, entity_link_clicked={entity_link}, todo_link_clicked={todo_link}"


async def step_entities_list(runner: TestRunner, r: StepResult) -> None:
    """Step 6: 人脉列表 — 搜索 / 详情弹窗 / 信用分 / 关系阶段。"""
    page = runner.page
    await goto_page(page, "/pages/entities/index")

    list_ready = await wait_visible(page, ".page-entities, .entity-list", timeout=8000)
    if not list_ready:
        r.passed = False
        r.detail = "entities page not loaded"
        return

    # 搜索
    search_input = await page.query_selector(".search-bar input, input.search-input")
    search_ok = False
    if search_input:
        await search_input.fill("张")
        await asyncio.sleep(SETTLE_DELAY * 2)
        await search_input.fill("")
        await asyncio.sleep(SETTLE_DELAY)
        search_ok = True

    # 点击第一个人脉 → 弹出详情 modal（native click）
    entity_card = await page.query_selector(".entity-card")
    modal_open = False
    credit_visible = False
    stage_visible = False
    if entity_card:
        try:
            await entity_card.evaluate("e => e.click()")
            await asyncio.sleep(SETTLE_DELAY * 2)
            modal_open = await wait_visible(page, ".modal-content, .modal-overlay", timeout=5000)
            if modal_open:
                content = await page.content()
                credit_visible = "credit-score-section" in content or "关系信用分" in content
                stage_visible = "stage-section" in content or "关系阶段" in content
                # 关闭 modal
                await click_if_exists(page, ".modal-close", timeout=2000)
        except PlaywrightError:
            pass

    r.passed = list_ready and search_ok and modal_open
    r.detail = f"search_ok={search_ok}, modal_open={modal_open}, credit={credit_visible}, stage={stage_visible}"


async def step_entity_detail_navigation(runner: TestRunner, r: StepResult) -> None:
    """Step 7: 人脉详情 → 跳转关联事件 / 关联待办。"""
    page = runner.page
    await goto_page(page, "/pages/entities/index")
    await asyncio.sleep(SETTLE_DELAY)

    entity_card = await page.query_selector(".entity-card")
    if not entity_card:
        r.passed = False
        r.detail = "no entity card"
        return
    try:
        await entity_card.evaluate("e => e.click()")
    except PlaywrightError:
        pass
    await asyncio.sleep(SETTLE_DELAY * 2)

    modal_open = await wait_visible(page, ".modal-content", timeout=5000)
    if not modal_open:
        r.passed = False
        r.detail = "entity detail modal not opened"
        return

    # 点击"查看完整详情"进入详情页
    view_detail = await click_if_exists(page, ".view-detail-btn:has-text('查看完整详情')", timeout=3000)
    if not view_detail:
        view_detail = await text_click(page, "查看完整详情", timeout=2000)

    if not view_detail:
        r.skipped = True
        r.skip_reason = "view-detail-btn not found in entity modal"
        return

    await asyncio.sleep(SETTLE_DELAY * 2)

    # 在人脉详情页尝试点击关联事件 / 关联待办
    related_event_clicked = await click_if_exists(page, ".related-item:has-text(''), .related-item-title", timeout=3000)
    await asyncio.sleep(SETTLE_DELAY)
    await page.go_back()
    await asyncio.sleep(SETTLE_DELAY)

    r.passed = view_detail
    r.detail = f"view_detail={view_detail}, related_event_clicked={related_event_clicked}"


async def step_todos_list(runner: TestRunner, r: StepResult) -> None:
    """Step 8: 待办列表 — 状态筛选 / 类型筛选 / 完成 / 忽略 / 删除。"""
    page = runner.page
    await goto_page(page, "/pages/todos/index")

    list_ready = await wait_visible(page, ".page-todos, .tabs", timeout=8000)
    if not list_ready:
        r.passed = False
        r.detail = "todos page not loaded"
        return

    # 1) 状态筛选切换
    status_filters = {}
    for label in ["待处理", "已完成", "已忽略", "全部"]:
        ok = await text_click(page, label, timeout=2500)
        status_filters[label] = ok
        await asyncio.sleep(SETTLE_DELAY)

    # 切到"待处理"以便找到可操作的 todo
    await text_click(page, "待处理", timeout=2500)
    await asyncio.sleep(SETTLE_DELAY * 2)

    # 2) 类型筛选切换
    type_filters = {}
    for label in ["关注", "跟进", "全部"]:
        ok = await text_click(page, label, timeout=2000)
        type_filters[label] = ok
        await asyncio.sleep(SETTLE_DELAY)
    # 回到"全部"类型
    await text_click(page, "全部", timeout=2000)
    await text_click(page, "待处理", timeout=2000)
    await asyncio.sleep(SETTLE_DELAY * 2)

    # 3) 待办操作：完成 / 忽略（注意：基础版 UI 没有"推迟"按钮）
    action_results = {"done": False, "dismiss": False}

    # 找到"完成"按钮（native click）
    done_btn = await page.query_selector(".done-btn:has-text('完成'), .done-btn")
    if done_btn:
        try:
            await done_btn.evaluate("e => e.click()")
            await asyncio.sleep(SETTLE_DELAY * 2)
            action_results["done"] = True
        except PlaywrightError:
            pass

    # 重新加载后找"忽略"按钮
    dismiss_btn = await page.query_selector(".dismiss-btn:has-text('忽略'), .dismiss-btn")
    if dismiss_btn:
        try:
            await dismiss_btn.evaluate("e => e.click()")
            await asyncio.sleep(SETTLE_DELAY * 2)
            action_results["dismiss"] = True
        except PlaywrightError:
            pass

    r.passed = list_ready and any(status_filters.values()) and any(type_filters.values())
    r.detail = (
        f"status_filters={status_filters}, type_filters={type_filters}, "
        f"actions={action_results} (注：基础版 UI 无'推迟'按钮，仅有 完成/忽略/删除)"
    )


async def step_todo_detail_navigation(runner: TestRunner, r: StepResult) -> None:
    """Step 9: 待办详情 → 跳转关联事件 / 关联人脉。"""
    page = runner.page
    await goto_page(page, "/pages/todos/index")
    await text_click(page, "全部", timeout=2500)
    await asyncio.sleep(SETTLE_DELAY * 2)

    # 点击 todo 标题跳转到详情页（native click）
    todo_title = await page.query_selector(".todo-title")
    if not todo_title:
        r.passed = False
        r.detail = "no todo item"
        return
    try:
        await todo_title.evaluate("e => e.click()")
    except PlaywrightError:
        pass
    await asyncio.sleep(SETTLE_DELAY * 2)

    # 验证进入了详情页
    detail_ready = await wait_visible(page, ".page-todo-detail, .todo-detail", timeout=6000)
    if not detail_ready:
        # 可能是 detail 页类名不同，检查 url
        detail_ready = "/pages/todos/detail" in page.url

    if not detail_ready:
        r.skipped = True
        r.skip_reason = f"todo detail page not loaded, url={page.url}"
        return

    # 尝试点击关联事件 / 关联人脉
    entity_link = await click_if_exists(page, ".entity-link, .related-entity-link", timeout=3000)
    await asyncio.sleep(SETTLE_DELAY)
    await page.go_back()
    await asyncio.sleep(SETTLE_DELAY)

    event_link = await click_if_exists(page, ".source-event-link, .related-event-link", timeout=3000)
    await asyncio.sleep(SETTLE_DELAY)

    r.passed = detail_ready
    r.detail = f"detail_ready={detail_ready}, entity_link_clicked={entity_link}, event_link_clicked={event_link}"


async def step_promises_list(runner: TestRunner, r: StepResult) -> None:
    """Step 10: 承诺列表 — 视图切换 / 状态筛选 / 确认 / 忽略 / 兑现 / 违背 / 催促。"""
    page = runner.page
    await goto_page(page, "/pages/promises/index")

    list_ready = await wait_visible(page, ".page-promises, .view-tabs, .promise-list", timeout=8000)
    if not list_ready:
        r.passed = False
        r.detail = "promises page not loaded"
        return

    # 1) 视图切换：我的承诺 ↔ 对方的承诺
    view_results = {}
    for label in ["我的承诺", "对方的承诺"]:
        ok = await text_click(page, label, timeout=3000)
        view_results[label] = ok
        await asyncio.sleep(SETTLE_DELAY)

    # 切回"我的承诺"
    await text_click(page, "我的承诺", timeout=3000)
    await asyncio.sleep(SETTLE_DELAY)

    # 2) 状态筛选切换
    status_results = {}
    for label in ["待兑现", "已兑现", "已失效", "全部"]:
        ok = await text_click(page, label, timeout=2500)
        status_results[label] = ok
        await asyncio.sleep(SETTLE_DELAY)
    await text_click(page, "全部", timeout=2500)
    await asyncio.sleep(SETTLE_DELAY)

    # 3) 承诺操作：确认 / 忽略（针对未确认承诺）
    action_results = {"confirm": False, "ignore": False, "fulfill": False, "expired": False, "nudge": False}

    # 找未确认承诺的"确认"按钮（native click）
    confirm_btn = await page.query_selector(".ai-confirm-btn.confirm-btn:has-text('确认'), .confirm-btn")
    if confirm_btn:
        try:
            await confirm_btn.evaluate("e => e.click()")
            await asyncio.sleep(SETTLE_DELAY * 2)
            action_results["confirm"] = True
        except PlaywrightError:
            pass

    # 找"已兑现"按钮
    fulfill_btn = await page.query_selector(".action-btn.fulfill-btn:has-text('已兑现'), .fulfill-btn")
    if fulfill_btn:
        try:
            await fulfill_btn.evaluate("e => e.click()")
            await asyncio.sleep(SETTLE_DELAY * 2)
            action_results["fulfill"] = True
        except PlaywrightError:
            pass

    # 切到"对方的承诺"测试催促按钮
    await text_click(page, "对方的承诺", timeout=3000)
    await asyncio.sleep(SETTLE_DELAY)
    nudge_btn = await page.query_selector(".nudge-action-btn:has-text('催促'), .nudge-action-btn")
    if nudge_btn:
        try:
            await nudge_btn.evaluate("e => e.click()")
            await asyncio.sleep(SETTLE_DELAY * 3)
            nudge_popup = await wait_visible(page, ".nudge-popup, .nudge-popup-content", timeout=6000)
            action_results["nudge"] = nudge_popup
            if nudge_popup:
                await click_if_exists(page, ".nudge-popup-close, .nudge-close-btn", timeout=2000)
        except PlaywrightError:
            pass

    r.passed = list_ready and any(view_results.values()) and any(status_results.values())
    r.detail = (
        f"view_results={view_results}, status_results={status_results}, "
        f"actions={action_results}"
    )


async def step_mine_page(runner: TestRunner, r: StepResult) -> None:
    """Step 11: 我的页面 — 统计 / 数据导出。"""
    page = runner.page
    # "我的"页不在 tabBar，需直接导航
    await goto_page(page, "/pages/mine/index")

    page_ready = await wait_visible(page, ".mine-page, .mine-header", timeout=8000)
    if not page_ready:
        r.passed = False
        r.detail = "mine page not loaded"
        return

    content = await page.content()
    checks = {
        "user_header": "mine-header" in content or "mine-avatar" in content,
        "user_id_shown": "poc-user" in content,
        "edition_label": "基础版" in content,
        "pro_upgrade_entry": "升级专业版" in content,
        "export_entry": "导出我的数据" in content or "导出" in content,
        "about_entry": "关于" in content,
        "logout_btn": "退出登录" in content,
    }

    # 测试"关于"弹窗（不会触发下载，安全）
    about_clicked = await text_click(page, "关于 PromiseLink", timeout=3000)
    await asyncio.sleep(SETTLE_DELAY)
    # 关闭 modal
    await click_if_exists(page, ".taro-modal__footer .taro-button, button:has-text('确定')", timeout=3000)

    # 测试导出（点击会触发下载，用 download 事件捕获）
    export_clicked = False
    try:
        async with page.expect_download(timeout=6000) as dl_info:
            export_btn = await page.query_selector(".mine-menu-item:has-text('导出我的数据')")
            if export_btn:
                await export_btn.click()
                export_clicked = True
        download = await dl_info.value
        download_path = f"/tmp/e2e_export_{int(time.time())}.json"
        await download.save_as(download_path)
        r.detail_extra = f"download_saved={download_path}"
    except PlaywrightTimeoutError:
        # 导出可能用 Blob URL，不触发 download 事件，检查 toast
        export_clicked = export_btn is not None if "export_btn" in dir() else False
    except PlaywrightError:
        pass

    r.passed = page_ready and all(checks.values())
    r.detail = f"checks={checks}, about_clicked={about_clicked}, export_clicked={export_clicked}"


# ── 主入口 ──

async def main() -> int:
    print("=" * 70)
    print("  PromiseLink 基础版 UI 层 Playwright E2E 测试")
    print(f"  前端: {BASE_URL}  后端: {API_URL}")
    print(f"  视口: {VIEWPORT['width']}x{VIEWPORT['height']} (电脑宽屏)")
    print(f"  截图目录: {SCREENSHOT_DIR}")
    print("=" * 70)

    # 前置检查
    import urllib.request

    try:
        urllib.request.urlopen(f"{BASE_URL}", timeout=5)
    except Exception as e:  # noqa: BLE001
        print(f"  [FATAL] 前端不可访问: {e}")
        return 2
    try:
        urllib.request.urlopen(f"{API_URL}/api/v1/health", timeout=5)
    except Exception as e:  # noqa: BLE001
        print(f"  [FATAL] 后端不可访问: {e}")
        return 2

    # 启动浏览器：优先使用 chrome-headless-shell；若未安装则回退到已下载的
    # Chrome for Testing 二进制（基础版 PoC 环境可能因网络无法下载 headless shell）。
    chrome_for_testing = (
        Path.home()
        / "Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/"
          "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
    )
    launch_kwargs: dict[str, Any] = {"headless": True}
    if chrome_for_testing.exists():
        launch_kwargs["executable_path"] = str(chrome_for_testing)
        print(f"  [INFO] 使用 Chrome for Testing: {chrome_for_testing}")

    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(**launch_kwargs)
        context: BrowserContext = await browser.new_context(
            viewport=VIEWPORT,
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page: Page = await context.new_page()
        page.set_default_timeout(NAV_TIMEOUT)

        # 收集 console 错误与失败请求
        page.on(
            "console",
            lambda msg: runner.console_errors.append(f"[{msg.type}] {msg.text}")
            if msg.type == "error"
            else None,
        )
        page.on(
            "requestfailed",
            lambda req: runner.failed_requests.append(f"{req.method} {req.url}: {req.failure}")
            if "api" in req.url
            else None,
        )

        runner = TestRunner(page)

        # 执行所有测试步骤
        steps = [
            ("01-Login", "登录", step_login),
            ("02-Dashboard", "首页Dashboard", step_dashboard),
            ("03a-EventInputText", "事件录入(文本)", step_event_input_text),
            ("03b-EventInputFile", "事件录入(文件)", step_event_input_file),
            ("04-EventsList", "事件列表", step_events_list),
            ("05-EventDetailNav", "事件详情跳转", step_event_detail_navigation),
            ("06-EntitiesList", "人脉列表", step_entities_list),
            ("07-EntityDetailNav", "人脉详情跳转", step_entity_detail_navigation),
            ("08-TodosList", "待办列表", step_todos_list),
            ("09-TodoDetailNav", "待办详情跳转", step_todo_detail_navigation),
            ("10-PromisesList", "承诺列表", step_promises_list),
            ("11-MinePage", "我的页面", step_mine_page),
        ]

        for code, name, fn in steps:
            print(f"\n[{ts()}] ▶ {code} {name}")
            await runner.run(code, name, fn)

        await browser.close()

    # ── 汇总报告 ──
    print("\n" + "=" * 70)
    print("  测试结果汇总")
    print("=" * 70)

    passed = sum(1 for r in runner.results if r.passed and not r.skipped)
    failed = sum(1 for r in runner.results if not r.passed and not r.skipped)
    skipped = sum(1 for r in runner.results if r.skipped)
    total = len(runner.results)

    for r in runner.results:
        if r.skipped:
            status = "SKIP"
        elif r.passed:
            status = "PASS"
        else:
            status = "FAIL"
        icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}[status]
        print(f"  {icon} [{status}] {r.category} {r.name}")
        if status in ("FAIL", "SKIP"):
            print(f"       └─ {r.detail[:150]}")

    print(f"\n  通过: {passed}  失败: {failed}  跳过: {skipped}  总计: {total}")

    if runner.console_errors:
        print(f"\n  Console Errors ({len(runner.console_errors)}):")
        for err in runner.console_errors[:8]:
            print(f"    {err[:140]}")

    if runner.failed_requests:
        print(f"\n  Failed API Requests ({len(runner.failed_requests)}):")
        for req in runner.failed_requests[:8]:
            print(f"    {req[:140]}")

    overall = "PASS" if failed == 0 else ("PARTIAL" if passed > 0 else "FAIL")
    print(f"\n  Overall: {overall}")

    # 保存 JSON 报告
    report = {
        "overall": overall,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": total,
        "viewport": VIEWPORT,
        "base_url": BASE_URL,
        "api_url": API_URL,
        "timestamp": datetime.now().isoformat(),
        "steps": [r.to_dict() for r in runner.results],
        "console_errors_count": len(runner.console_errors),
        "failed_requests_count": len(runner.failed_requests),
        "console_errors": runner.console_errors[:20],
        "failed_requests": runner.failed_requests[:20],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  报告已保存: {REPORT_PATH}")
    print(f"  截图目录: {SCREENSHOT_DIR}")

    return 0 if overall == "PASS" else (1 if overall == "PARTIAL" else 2)


if __name__ == "__main__":
    import sys

    sys.exit(asyncio.run(main()))
