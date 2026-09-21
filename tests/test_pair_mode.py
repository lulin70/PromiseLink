"""Tests for promiselink.api.v1.pair — device pairing mode for one-click install.

Covers:
- POST /api/v1/pair/init   — desktop initializes pairing (calls gateway)
- GET  /api/v1/pair/status — desktop polls pairing status (calls gateway)
- POST /api/v1/pair/activate — desktop activates with license_key (writes .env)
- GET  /pair               — pairing HTML page

Uses a mock httpx module (types.ModuleType) to isolate gateway mocking from
the global httpx used by TestClient's ASGI transport.
"""

from __future__ import annotations

import asyncio
import json
import types

import httpx
import pytest
from fastapi.testclient import TestClient

from promiselink.api.v1 import pair as pair_module

# ── Helpers ──


def _gateway_init_response() -> dict:
    """Simulated gateway response for POST /api/v1/pair/device."""
    return {
        "data": {
            "device_pair_code": "384721",
            "device_fingerprint": "sha256:test-fp",
            "expires_in": 300,
            "qr_content": "https://www.promiselink.cn/pair?code=384721",
        }
    }


def _gateway_status_pending() -> dict:
    """Simulated gateway response for pending status."""
    return {
        "data": {
            "status": "pending",
            "license_key": None,
            "user_id": None,
        }
    }


def _gateway_status_matched() -> dict:
    """Simulated gateway response for matched status."""
    return {
        "data": {
            "status": "matched",
            "license_key": "PL-PRO-TEST-ABCD-EFGH",
            "user_id": "u_testuser",
        }
    }


def _mock_httpx_module(handler) -> types.ModuleType:
    """Create a mock httpx module that only replaces AsyncClient.

    Other attributes (Timeout, HTTPError) delegate to the real httpx so
    module-level constants like _GATEWAY_TIMEOUT remain valid.
    """
    mock = types.ModuleType("mock_httpx")
    mock.Timeout = httpx.Timeout
    mock.HTTPError = httpx.HTTPError
    mock.ConnectError = httpx.ConnectError

    def _async_client(**kwargs):
        kwargs.pop("timeout", None)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    mock.AsyncClient = _async_client
    return mock


# ── /pair/init tests ──


def test_pair_init_success(monkeypatch):
    """POST /api/v1/pair/init returns code + QR content from gateway."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/pair/device"
        return httpx.Response(200, json=_gateway_init_response())

    monkeypatch.setattr(pair_module, "httpx", _mock_httpx_module(handler))

    from promiselink.main import app

    with TestClient(app) as client:
        resp = client.post("/api/v1/pair/init")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["device_pair_code"] == "384721"
    assert data["qr_content"] == "https://www.promiselink.cn/pair?code=384721"
    assert data["expires_in"] == 300


def test_pair_init_gateway_unreachable(monkeypatch):
    """POST /api/v1/pair/init returns error when gateway is unreachable."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(pair_module, "httpx", _mock_httpx_module(handler))

    from promiselink.main import app

    with TestClient(app) as client:
        resp = client.post("/api/v1/pair/init")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "无法连接网关" in data["error"]


def test_pair_init_gateway_error_status(monkeypatch):
    """POST /api/v1/pair/init returns error when gateway returns non-200."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "Internal error"}})

    monkeypatch.setattr(pair_module, "httpx", _mock_httpx_module(handler))

    from promiselink.main import app

    with TestClient(app) as client:
        resp = client.post("/api/v1/pair/init")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "500" in data["error"]


def test_pair_init_empty_exception_message_still_names_the_failure(monkeypatch):
    """L-15: 异常信息为空串时，错误提示仍须带上异常类型。

    干净环境 e2e 在真实网关上实测到一次 `str(exc) == ""`
    （4 次调用中出现 1 次），此时旧提示是「无法连接网关: 」，用户拿不到
    任何可用于排查的线索。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("")

    monkeypatch.setattr(pair_module, "httpx", _mock_httpx_module(handler))

    from promiselink.main import app

    with TestClient(app) as client:
        resp = client.post("/api/v1/pair/init")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "ConnectError" in data["error"]


# ── /pair/status tests ──


def test_pair_status_pending(monkeypatch):
    """GET /api/v1/pair/status returns pending."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_gateway_status_pending())

    monkeypatch.setattr(pair_module, "httpx", _mock_httpx_module(handler))

    from promiselink.main import app

    with TestClient(app) as client:
        resp = client.get("/api/v1/pair/status", params={"code": "384721"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "pending"


def test_pair_status_matched(monkeypatch):
    """GET /api/v1/pair/status returns matched with license_key."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_gateway_status_matched())

    monkeypatch.setattr(pair_module, "httpx", _mock_httpx_module(handler))

    from promiselink.main import app

    with TestClient(app) as client:
        resp = client.get("/api/v1/pair/status", params={"code": "384721"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "matched"
    assert data["license_key"] == "PL-PRO-TEST-ABCD-EFGH"


def test_pair_status_gateway_error(monkeypatch):
    """GET /api/v1/pair/status returns error on gateway failure."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(pair_module, "httpx", _mock_httpx_module(handler))

    from promiselink.main import app

    with TestClient(app) as client:
        resp = client.get("/api/v1/pair/status", params={"code": "384721"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "无法连接网关" in data["error"]


# ── /pair/activate tests ──


def test_pair_activate_success(monkeypatch, tmp_path):
    """POST /api/v1/pair/activate writes license_key to .env."""
    fake_env = tmp_path / ".env"
    fake_env.write_text("APP_ENV=development\nSECRET_KEY=test-secret\n", encoding="utf-8")

    monkeypatch.setattr(pair_module, "_get_env_path", lambda: fake_env)
    monkeypatch.delenv("PRO_LICENSE_KEY", raising=False)

    from promiselink.main import app

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/pair/activate",
            json={"license_key": "PL-PRO-ACTIVATE-001"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "专业版激活成功" in data["message"]

    content = fake_env.read_text(encoding="utf-8")
    assert "PRO_LICENSE_KEY=PL-PRO-ACTIVATE-001" in content


def test_pair_activate_overwrites_existing(monkeypatch, tmp_path):
    """POST /api/v1/pair/activate overwrites existing PRO_LICENSE_KEY in .env."""
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "APP_ENV=development\nPRO_LICENSE_KEY=PL-PRO-OLD-KEY\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(pair_module, "_get_env_path", lambda: fake_env)

    from promiselink.main import app

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/pair/activate",
            json={"license_key": "PL-PRO-NEW-KEY"},
        )

    assert resp.status_code == 200
    content = fake_env.read_text(encoding="utf-8")
    assert "PRO_LICENSE_KEY=PL-PRO-NEW-KEY" in content
    assert "PL-PRO-OLD-KEY" not in content


def test_pair_activate_empty_key(monkeypatch, tmp_path):
    """POST /api/v1/pair/activate rejects empty license_key."""
    from promiselink.main import app

    with TestClient(app) as client:
        resp = client.post("/api/v1/pair/activate", json={"license_key": ""})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "不能为空" in data["error"]


def test_pair_activate_whitespace_trimmed(monkeypatch, tmp_path):
    """POST /api/v1/pair/activate trims whitespace from license_key."""
    fake_env = tmp_path / ".env"
    fake_env.write_text("APP_ENV=development\n", encoding="utf-8")

    monkeypatch.setattr(pair_module, "_get_env_path", lambda: fake_env)

    from promiselink.main import app

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/pair/activate",
            json={"license_key": "  PL-PRO-TRIM-TEST  "},
        )

    assert resp.status_code == 200
    content = fake_env.read_text(encoding="utf-8")
    assert "PRO_LICENSE_KEY=PL-PRO-TRIM-TEST" in content


# ── /pair HTML page tests ──


def test_pair_page_returns_html():
    """GET /pair returns HTML page with pairing UI."""
    from promiselink.main import app

    with TestClient(app) as client:
        resp = client.get("/pair")

    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    body = resp.text
    assert "PromiseLink" in body or "配对" in body


# ── Full flow integration test ──


def test_full_pair_flow_init_to_activate(monkeypatch, tmp_path):
    """Full pairing flow: init → status(pending) → status(matched) → activate."""
    fake_env = tmp_path / ".env"
    fake_env.write_text("APP_ENV=development\nSECRET_KEY=test\n", encoding="utf-8")

    gateway_state = {"status": "pending"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v1/pair/device":
            return httpx.Response(200, json=_gateway_init_response())
        if request.method == "GET" and "/api/v1/pair/device/" in str(request.url.path):
            if gateway_state["status"] == "pending":
                return httpx.Response(200, json=_gateway_status_pending())
            return httpx.Response(200, json=_gateway_status_matched())
        return httpx.Response(404)

    monkeypatch.setattr(pair_module, "httpx", _mock_httpx_module(handler))
    monkeypatch.setattr(pair_module, "_get_env_path", lambda: fake_env)

    from promiselink.main import app

    with TestClient(app) as client:
        # 1. Init
        resp = client.post("/api/v1/pair/init")
        assert resp.json()["success"] is True
        code = resp.json()["device_pair_code"]

        # 2. Status — pending
        resp = client.get("/api/v1/pair/status", params={"code": code})
        assert resp.json()["status"] == "pending"

        # 3. Simulate miniapp scan → gateway now matched
        gateway_state["status"] = "matched"

        # 4. Status — matched
        resp = client.get("/api/v1/pair/status", params={"code": code})
        assert resp.json()["status"] == "matched"
        license_key = resp.json()["license_key"]

        # 5. Activate
        resp = client.post("/api/v1/pair/activate", json={"license_key": license_key})
        assert resp.json()["success"] is True

    content = fake_env.read_text(encoding="utf-8")
    assert f"PRO_LICENSE_KEY={license_key}" in content


# ── auto-pair 轮询任务可重建（2026-09-20 回归） ──
#
# 缺陷：``_pair_auto_poll`` 只在 App 启动时被创建一次，到达 10 分钟上限就
# ``return`` 且不再重建。配对码只有 5 分钟有效期，因此用户第一次配对超时后
# 再点「配对」，不重启 App 就再也配不上（现场只能靠临时脚本复刻轮询绕过）。


async def test_auto_poll_recovers_after_timeout_when_pairing_retried(monkeypatch, tmp_path):
    """回归：第一轮轮询超时退出后，重新发起配对仍能完成激活。

    完整时序：无配对码 → 第一轮轮询到上限退出（复现「配对码已过期」）→
    ``POST /pair/init`` 落盘新配对码并重启轮询 → 网关 matched →
    本地 ``/pair/activate`` 被调用 → 配对码文件清理。
    """
    from promiselink import main as main_module

    pair_code_file = tmp_path / ".pair_code"
    gateway_state = {"status": "pending"}
    activated: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.startswith("/api/v1/pair/device/"):
            if gateway_state["status"] == "matched":
                return httpx.Response(200, json=_gateway_status_matched())
            return httpx.Response(200, json=_gateway_status_pending())
        if request.method == "POST" and path == "/api/v1/pair/activate":
            activated.append(json.loads(request.content)["license_key"])
            return httpx.Response(200, json={"success": True, "message": "ok"})
        raise AssertionError(f"unexpected request: {request.method} {path}")

    monkeypatch.setattr(main_module, "httpx", _mock_httpx_module(handler))
    monkeypatch.setattr(main_module, "runtime_pair_code_file", lambda: pair_code_file)
    monkeypatch.setattr(main_module, "get_settings", lambda: types.SimpleNamespace(pro_license_key="", api_port=8000))
    monkeypatch.setattr(main_module, "_PAIR_POLL_INITIAL_DELAY", 0)
    monkeypatch.setattr(main_module, "_PAIR_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(main_module, "_pair_poll_task", None)

    # 第一轮：没有配对码，轮询到达上限即退出（复现「配对码已过期」）
    monkeypatch.setattr(main_module, "_PAIR_POLL_MAX_RUNTIME", 0.02)
    await asyncio.wait_for(main_module._pair_auto_poll(), timeout=5)
    assert not pair_code_file.exists()

    # 第二轮：用户重新发起配对 —— 新配对码落盘 + 轮询任务重建
    monkeypatch.setattr(main_module, "_PAIR_POLL_MAX_RUNTIME", 10)
    pair_code_file.write_text("384721")
    gateway_state["status"] = "matched"

    task = main_module.start_pair_auto_poll()
    await asyncio.wait_for(task, timeout=5)

    assert activated == ["PL-PRO-TEST-ABCD-EFGH"]
    assert not pair_code_file.exists(), "激活成功后应清理配对码文件"


async def test_start_pair_auto_poll_replaces_running_poller(monkeypatch):
    """重新发起配对必须取消仍在跑的旧轮询，让新配对码拿到完整的轮询窗口。

    否则旧任务可能只剩几秒就到期，用户刚拿到的新配对码会被它一起带走。
    """
    from promiselink import main as main_module

    async def _never_ending() -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(main_module, "_pair_auto_poll", _never_ending)
    monkeypatch.setattr(main_module, "_pair_poll_task", None)

    first = main_module.start_pair_auto_poll()
    await asyncio.sleep(0)
    second = main_module.start_pair_auto_poll()
    await asyncio.gather(first, return_exceptions=True)

    assert first.cancelled() is True
    assert second is not first
    assert main_module._pair_poll_task is second

    second.cancel()
    await asyncio.gather(second, return_exceptions=True)


async def test_pair_init_starts_the_auto_poll_task(monkeypatch, tmp_path):
    """回归：``POST /pair/init`` 必须自己拉起轮询任务。

    修复前 init 只写文件、从不碰轮询 —— 这正是「超时后必须重启 App」的根因。
    """
    from promiselink import main as main_module

    pair_code_file = tmp_path / ".pair_code"
    restarts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_gateway_init_response())

    monkeypatch.setattr(pair_module, "httpx", _mock_httpx_module(handler))
    monkeypatch.setattr(pair_module, "runtime_pair_code_file", lambda: pair_code_file)
    monkeypatch.setattr(main_module, "start_pair_auto_poll", lambda: restarts.append(1))

    resp = await pair_module.init_pair()

    assert resp.success is True
    assert pair_code_file.read_text(encoding="utf-8") == "384721"
    assert restarts == [1]
