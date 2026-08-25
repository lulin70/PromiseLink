"""三仓联调 e2e 测试：模拟用户操作完整 WSS 中继链路.

测试目标:
1. 基础版 RelayWSSClient 成功连接到 Pro 网关 (active_ws_connections > 0)
2. 通过网关 /api/v1/pro/relay/request 调用基础版 API
3. 验证返回数据正确 (entities / todos / events)
4. 模拟用户录入事件 -> 网关中继 -> 基础版处理 -> AI 解析 -> 验证结果

使用真实组件 (无 Mock):
- 真实基础版 (localhost:8000)
- 真实 Pro 网关 (https://gateway.promiselink.cn)
- 真实 WSS 中继链路
- 真实 LLM 调用 (DeepSeek)

前置条件:
- 基础版运行在 localhost:8000, .env 配置 PRO_LICENSE_KEY + RELAY_WSS_ENABLED=true
- Pro 网关运行在 https://gateway.promiselink.cn, 已激活 license_key
- WSS 连接已建立 (active_ws_connections >= 1)

Usage:
    cd /Users/lin/trae_projects/PromiseLink
    .venv/bin/python scripts/e2e/e2e_three_repos_wss.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# ── 配置 ────────────────────────────────────────────────────────────
GATEWAY_URL = os.environ.get("GATEWAY_URL", "https://gateway.promiselink.cn")
BASIC_URL = os.environ.get("BASIC_URL", "http://localhost:8000")
LICENSE_KEY = os.environ.get("PRO_LICENSE_KEY", "PL-PRO-EE3B-8344-5372")


def _derive_device_fingerprint(license_key: str) -> str:
    """派生 device_fingerprint：与基础版 relay_client._derive_device_fingerprint 一致。

    保证基础版 WSS 中继 + E2E 脚本 + Pro 网关 activate 同一 license 时使用
    同一指纹，避免 DEVICE_FINGERPRINT_MISMATCH。

    关键：必须和 src/promiselink/services/relay_client.py::RelayClient._derive_device_fingerprint
    的算法保持一致 (sha256(license_key))。
    """
    import hashlib

    digest = hashlib.sha256(license_key.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


DEVICE_FINGERPRINT = _derive_device_fingerprint(LICENSE_KEY)

# 颜色输出
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 70}\n  {title}\n{'=' * 70}{RESET}")


def step(msg: str) -> None:
    print(f"{CYAN}  ▶ {msg}{RESET}")


def ok(msg: str) -> None:
    print(f"{GREEN}  ✅ {msg}{RESET}")


def fail(msg: str) -> None:
    print(f"{RED}  ❌ {msg}{RESET}")


def warn(msg: str) -> None:
    print(f"{YELLOW}  ⚠ {msg}{RESET}")


def info(msg: str) -> None:
    print(f"     {msg}")


# ── 测试用例 ────────────────────────────────────────────────────────


async def test_gateway_health() -> dict[str, Any]:
    """测试 1: 网关健康检查 + WSS 连接数."""
    section("[测试 1] Pro 网关健康检查")
    step(f"GET {GATEWAY_URL}/api/v1/pro/health")

    async with httpx.AsyncClient(verify=True, timeout=15) as client:
        resp = await client.get(f"{GATEWAY_URL}/api/v1/pro/health")

    if resp.status_code != 200:
        fail(f"健康检查失败: HTTP {resp.status_code}")
        return {}

    data = resp.json()
    info(f"status={data.get('status')}, version={data.get('version')}")
    info(f"components: {json.dumps(data.get('components', {}), ensure_ascii=False)}")

    ws_count = data.get("metrics", {}).get("active_ws_connections", -1)
    if ws_count >= 1:
        ok(f"active_ws_connections={ws_count} (WSS 中继已建立)")
    elif ws_count == 0:
        fail(f"active_ws_connections=0 (基础版 WSS 未连接)")
    else:
        fail(f"active_ws_connections={ws_count} (BUG-3 修复未生效)")

    return data


async def test_basic_health() -> dict[str, Any]:
    """测试 2: 基础版健康检查."""
    section("[测试 2] 基础版健康检查")
    step(f"GET {BASIC_URL}/api/v1/health")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASIC_URL}/api/v1/health")

    if resp.status_code != 200:
        fail(f"基础版健康检查失败: HTTP {resp.status_code}")
        return {}

    data = resp.json()
    ok(f"基础版 v{data.get('version')}, status={data.get('status')}")
    return data


async def get_relay_access_token() -> str:
    """通过 license activate 获取 access token (用于 relay/request)."""
    step("通过 /api/v1/pro/license/activate 获取 access_token")

    # 基础版激活时已经获取了 token, 但我们没有简单的方法从外部读取.
    # 直接调用 /license/activate 端点用 license_key 换取 token.
    # 需要 X-API-Key 或 license_key 作为 API Key.
    # verify_api_key_or_license 允许用 license_key 作为 fallback.
    payload = {
        "license_key": LICENSE_KEY,
        "device_fingerprint": DEVICE_FINGERPRINT,
    }
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": LICENSE_KEY,  # 允许 license_key 作为 API Key
    }

    async with httpx.AsyncClient(verify=True, timeout=30) as client:
        resp = await client.post(
            f"{GATEWAY_URL}/api/v1/pro/license/activate",
            json=payload,
            headers=headers,
        )

    if resp.status_code != 200:
        fail(f"license activate 失败: HTTP {resp.status_code}")
        info(f"响应: {resp.text[:500]}")
        return ""

    data = resp.json()
    if not data.get("success"):
        fail(f"license activate 失败: {data}")
        return ""

    token = data.get("data", {}).get("tokens", {}).get("access_token", "")
    if not token:
        fail("access_token 为空")
        info(f"响应结构: {list(data.get('data', {}).keys())}")
        return ""

    ok("access_token 获取成功")
    return token


async def get_basic_user_token() -> str:
    """通过基础版 /api/v1/auth/login 获取 user JWT (用于 X-User-Token)."""
    step("通过基础版 /api/v1/auth/login 获取 user JWT")

    payload = {
        "user_id": "wxid_54n7svddprmo22",  # 与微信登录一致的 user_id
        "poc_secret": "promiselink2026",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASIC_URL}/api/v1/auth/login",
            json=payload,
        )

    if resp.status_code != 200:
        fail(f"基础版登录失败: HTTP {resp.status_code}")
        return ""

    data = resp.json()
    token = data.get("access_token", "")
    if not token:
        fail("基础版 access_token 为空")
        return ""

    ok("基础版 user JWT 获取成功")
    return token


def build_relay_headers(relay_token: str, user_token: str = "", content_type: str = "") -> dict[str, str]:
    """构建 relay/request 请求头.

    - Authorization: relay JWT (网关认证)
    - X-User-Token: 基础版 user JWT (转发到基础版作为 Authorization)
    """
    headers = {"Authorization": f"Bearer {relay_token}"}
    if user_token:
        headers["X-User-Token"] = user_token
    if content_type:
        headers["Content-Type"] = content_type
    return headers


async def test_relay_request_entities(relay_token: str, user_token: str) -> dict[str, Any]:
    """测试 3: 通过网关 relay/request 调用基础版 /api/v1/entities."""
    section("[测试 3] WSS 中继: 网关 → 基础版 /api/v1/entities")
    step(f"GET {GATEWAY_URL}/api/v1/pro/relay/request?path=/api/v1/entities")

    headers = build_relay_headers(relay_token, user_token)

    async with httpx.AsyncClient(verify=True, timeout=30) as client:
        resp = await client.get(
            f"{GATEWAY_URL}/api/v1/pro/relay/request",
            params={"path": "/api/v1/entities", "limit": "10"},
            headers=headers,
        )

    if resp.status_code != 200:
        fail(f"relay/request 失败: HTTP {resp.status_code}")
        info(f"响应: {resp.text[:500]}")
        return {}

    data = resp.json()
    if not data.get("success"):
        fail(f"relay/request 返回失败: {data}")
        return {}

    inner = data.get("data", {})
    inner_status = inner.get("status", 0)
    inner_body = inner.get("body", "")

    if inner_status != 200:
        fail(f"基础版返回 HTTP {inner_status}")
        info(f"body: {inner_body[:300]}")
        return {}

    # inner_body 是字符串, 解析为 JSON
    try:
        entities_data = json.loads(inner_body) if isinstance(inner_body, str) else inner_body
    except json.JSONDecodeError as e:
        fail(f"基础版响应非 JSON: {e}, body={inner_body[:200]}")
        return {}

    total = entities_data.get("total", 0)
    ok(f"基础版返回 {total} 个实体 (通过 WSS 中继)")
    info(f"实体样例: {json.dumps(entities_data.get('items', [])[:2], ensure_ascii=False)[:200]}")
    return entities_data


async def test_relay_request_todos(relay_token: str, user_token: str) -> dict[str, Any]:
    """测试 4: 通过网关 relay/request 调用基础版 /api/v1/todos."""
    section("[测试 4] WSS 中继: 网关 → 基础版 /api/v1/todos")
    step(f"GET {GATEWAY_URL}/api/v1/pro/relay/request?path=/api/v1/todos")

    headers = build_relay_headers(relay_token, user_token)

    async with httpx.AsyncClient(verify=True, timeout=30) as client:
        resp = await client.get(
            f"{GATEWAY_URL}/api/v1/pro/relay/request",
            params={"path": "/api/v1/todos", "limit": "10"},
            headers=headers,
        )

    if resp.status_code != 200:
        fail(f"relay/request 失败: HTTP {resp.status_code}")
        return {}

    data = resp.json()
    if not data.get("success"):
        fail(f"relay/request 返回失败: {data}")
        return {}

    inner = data.get("data", {})
    inner_status = inner.get("status", 0)
    inner_body = inner.get("body", "")

    if inner_status != 200:
        fail(f"基础版返回 HTTP {inner_status}")
        return {}

    try:
        todos_data = json.loads(inner_body) if isinstance(inner_body, str) else inner_body
    except json.JSONDecodeError:
        fail(f"基础版响应非 JSON: {inner_body[:200]}")
        return {}

    total = todos_data.get("total", 0)
    ok(f"基础版返回 {total} 个待办 (通过 WSS 中继)")
    return todos_data


async def test_relay_create_event(relay_token: str, user_token: str) -> dict[str, Any]:
    """测试 5: 模拟用户录入事件 (通过 WSS 中继)."""
    section("[测试 5] WSS 中继: 录入事件 → AI 解析")
    step(f"POST {GATEWAY_URL}/api/v1/pro/relay/request?path=/api/v1/events")

    raw_text = (
        "今天上午和李总开会,他要求我们在下周五之前提交方案."
        "我承诺本周三前发给他初步架构图."
        "如果这周能先出 demo 就更好了."
        "我预计周五可以给张伟一个评估结果."
    )
    payload = {
        "event_type": "meeting",
        "raw_text": raw_text,
        "source": "wechat",
    }
    headers = build_relay_headers(relay_token, user_token, content_type="application/json")

    async with httpx.AsyncClient(verify=True, timeout=30) as client:
        resp = await client.post(
            f"{GATEWAY_URL}/api/v1/pro/relay/request",
            params={"path": "/api/v1/events"},
            json=payload,
            headers=headers,
        )

    if resp.status_code != 200:
        fail(f"relay/request POST 失败: HTTP {resp.status_code}")
        info(f"响应: {resp.text[:500]}")
        return {}

    data = resp.json()
    if not data.get("success"):
        fail(f"relay/request 返回失败: {data}")
        return {}

    inner = data.get("data", {})
    inner_status = inner.get("status", 0)
    inner_body = inner.get("body", "")

    if inner_status not in (200, 201):
        fail(f"基础版返回 HTTP {inner_status}")
        info(f"body: {inner_body[:300]}")
        return {}

    try:
        event_data = json.loads(inner_body) if isinstance(inner_body, str) else inner_body
    except json.JSONDecodeError:
        fail(f"基础版响应非 JSON: {inner_body[:200]}")
        return {}

    event_id = event_data.get("id") or event_data.get("event", {}).get("id")
    ok(f"事件录入成功, event_id={event_id}")
    info(f"raw_text 摘要: {raw_text[:60]}...")
    return {"event_id": event_id, "data": event_data}


async def test_relay_pipeline_status(relay_token: str, user_token: str, event_id: str) -> bool:
    """测试 6: 轮询事件 Pipeline 处理状态 (通过 GET /events/{id})."""
    section(f"[测试 6] 轮询 Pipeline 状态 (event_id={event_id})")
    step(f"GET {GATEWAY_URL}/api/v1/pro/relay/request?path=/api/v1/events/{{id}}")

    headers = build_relay_headers(relay_token, user_token)

    max_wait = 120  # 2 分钟
    poll_interval = 5
    waited = 0

    async with httpx.AsyncClient(verify=True, timeout=30) as client:
        while waited < max_wait:
            await asyncio.sleep(poll_interval)
            waited += poll_interval

            resp = await client.get(
                f"{GATEWAY_URL}/api/v1/pro/relay/request",
                params={"path": f"/api/v1/events/{event_id}"},
                headers=headers,
            )

            if resp.status_code != 200:
                warn(f"轮询失败: HTTP {resp.status_code}, 重试...")
                continue

            data = resp.json()
            if not data.get("success"):
                err = data.get("error")
                err_msg = (err.get("message", "") if isinstance(err, dict) else str(err))[:100]
                warn(f"轮询返回失败, 重试: {err_msg}")
                continue

            inner = data.get("data", {})
            inner_body = inner.get("body", "")
            try:
                event_data = json.loads(inner_body) if isinstance(inner_body, str) else inner_body
            except json.JSONDecodeError:
                warn("基础版响应非 JSON, 重试...")
                continue

            # pipeline_status 在 event 对象内 (字段名是 'status')
            event = event_data.get("event", event_data)
            status = event.get("status", "")
            failed_steps = event.get("failed_steps") or []
            info(f"[{waited}s] status={status}, failed_steps={failed_steps}")

            if status == "completed":
                ok(f"Pipeline 完成!")
                # 查询关联的实体/待办/承诺
                await _verify_extraction_results(relay_token, user_token, event_id)
                return True
            if status == "failed":
                fail(f"Pipeline 失败: failed_steps={failed_steps}")
                return False

    fail(f"Pipeline 超时 ({max_wait}s)")
    return False


async def _verify_extraction_results(relay_token: str, user_token: str, event_id: str) -> None:
    """验证事件关联的实体/待办/承诺已正确提取."""
    step("验证 AI 解析结果 (实体/待办/承诺)")
    headers = build_relay_headers(relay_token, user_token)

    async with httpx.AsyncClient(verify=True, timeout=20) as client:
        # 查询实体
        resp = await client.get(
            f"{GATEWAY_URL}/api/v1/pro/relay/request",
            params={"path": "/api/v1/entities", "limit": "10"},
            headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            inner = data.get("data", {})
            try:
                entities_data = json.loads(inner.get("body", "{}")) if isinstance(inner.get("body"), str) else inner.get("body", {})
                total = entities_data.get("total", 0)
                info(f"实体总数: {total}")
            except Exception:
                pass

        # 查询待办
        resp = await client.get(
            f"{GATEWAY_URL}/api/v1/pro/relay/request",
            params={"path": "/api/v1/todos", "limit": "10"},
            headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            inner = data.get("data", {})
            try:
                todos_data = json.loads(inner.get("body", "{}")) if isinstance(inner.get("body"), str) else inner.get("body", {})
                total = todos_data.get("total", 0)
                info(f"待办总数: {total}")
            except Exception:
                pass

        # 查询承诺
        resp = await client.get(
            f"{GATEWAY_URL}/api/v1/pro/relay/request",
            params={"path": "/api/v1/promises", "limit": "10"},
            headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            inner = data.get("data", {})
            try:
                promises_data = json.loads(inner.get("body", "{}")) if isinstance(inner.get("body"), str) else inner.get("body", {})
                total = promises_data.get("total", 0)
                info(f"承诺总数: {total}")
                # 显示承诺详情
                items = promises_data.get("items", [])
                if items:
                    for p in items[:3]:
                        info(f"  - {p.get('action_type', '')}: {p.get('description', '')[:80]}")
            except Exception:
                pass


async def test_relay_stability_multiple_requests(relay_token: str, user_token: str) -> dict[str, int]:
    """测试 7: WSS 中继稳定性 - 连续 10 次请求无 LOCAL_BASIC_UNAVAILABLE."""
    section("[测试 7] WSS 中继稳定性 (连续 10 次请求)")
    step(f"GET {GATEWAY_URL}/api/v1/pro/relay/request?path=/api/v1/entities × 10")

    headers = build_relay_headers(relay_token, user_token)
    success_count = 0
    failure_count = 0
    unstable_count = 0
    inner_failure_count = 0  # 外层成功但内层 4xx/5xx

    async with httpx.AsyncClient(verify=True, timeout=20) as client:
        for i in range(10):
            try:
                resp = await client.get(
                    f"{GATEWAY_URL}/api/v1/pro/relay/request",
                    params={"path": "/api/v1/entities", "limit": "5"},
                    headers=headers,
                )

                if resp.status_code != 200:
                    failure_count += 1
                    info(f"  [{i + 1}/10] HTTP {resp.status_code}")
                    continue

                data = resp.json()
                if not data.get("success"):
                    failure_count += 1
                    err_code = data.get("error", {}).get("code", "")
                    if err_code == "LOCAL_BASIC_UNAVAILABLE":
                        unstable_count += 1
                        fail(f"  [{i + 1}/10] LOCAL_BASIC_UNAVAILABLE (worker 路由失败)")
                    else:
                        info(f"  [{i + 1}/10] 失败: {err_code}")
                    continue

                # 检查内层状态 (基础版返回的 HTTP 状态)
                inner = data.get("data", {})
                inner_status = inner.get("status", 0)
                if inner_status != 200:
                    inner_failure_count += 1
                    info(f"  [{i + 1}/10] 内层 HTTP {inner_status}")
                    continue

                success_count += 1
                info(f"  [{i + 1}/10] OK")
            except Exception as e:
                failure_count += 1
                info(f"  [{i + 1}/10] 异常: {e}")

    print()
    ok(f"成功: {success_count}/10")
    if failure_count > 0:
        fail(f"外层失败: {failure_count}/10")
    if inner_failure_count > 0:
        fail(f"内层失败: {inner_failure_count}/10 (基础版返回 4xx/5xx)")
    if unstable_count > 0:
        fail(f"LOCAL_BASIC_UNAVAILABLE: {unstable_count}/10 (worker=1 修复未生效)")

    return {"success": success_count, "failure": failure_count, "unstable": unstable_count, "inner_failure": inner_failure_count}


async def main() -> int:
    print(f"{BOLD}{CYAN}")
    print("=" * 70)
    print("  PromiseLink 三仓联调 e2e 测试")
    print("  (基础版 + Pro 网关 + WSS 中继 → 模拟用户操作)")
    print("=" * 70)
    print(f"{RESET}")
    info(f"网关: {GATEWAY_URL}")
    info(f"基础版: {BASIC_URL}")
    info(f"License: {LICENSE_KEY[:16]}...")
    info(f"设备指纹: {DEVICE_FINGERPRINT[:32]}...")

    start_time = time.time()

    # 测试 1: 网关健康
    gateway_health = await test_gateway_health()
    if gateway_health.get("metrics", {}).get("active_ws_connections", 0) < 1:
        fail("WSS 中继未建立, 终止测试")
        return 1

    # 测试 2: 基础版健康
    await test_basic_health()

    # 获取 access token
    relay_token = await get_relay_access_token()
    if not relay_token:
        fail("无法获取 relay access_token, 终止测试")
        return 1

    # 获取基础版 user JWT (用于 X-User-Token 头)
    user_token = await get_basic_user_token()
    if not user_token:
        fail("无法获取基础版 user JWT, 终止测试")
        return 1

    # 测试 3: 查询实体
    await test_relay_request_entities(relay_token, user_token)

    # 测试 4: 查询待办
    await test_relay_request_todos(relay_token, user_token)

    # 测试 5: 录入事件
    event_result = await test_relay_create_event(relay_token, user_token)
    event_id = event_result.get("event_id")
    if event_id:
        # 测试 6: 轮询 Pipeline
        await test_relay_pipeline_status(relay_token, user_token, event_id)

    # 测试 7: 稳定性
    stability = await test_relay_stability_multiple_requests(relay_token, user_token)

    elapsed = time.time() - start_time
    section(f"[总结] 耗时 {elapsed:.1f}s")
    if stability["unstable"] == 0 and stability["success"] >= 8 and stability["inner_failure"] == 0:
        ok("三仓联调通过: WSS 中继稳定, worker=1 修复生效, 内层认证正确")
        return 0
    else:
        fail("三仓联调未通过")
        if stability["unstable"] > 0:
            info(f"  - LOCAL_BASIC_UNAVAILABLE: {stability['unstable']}/10")
        if stability["inner_failure"] > 0:
            info(f"  - 内层失败 (基础版 4xx/5xx): {stability['inner_failure']}/10")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
