"""Device pairing API endpoints for one-click Pro edition activation.

Endpoints:
- POST /api/v1/pair/init   — Desktop initializes pairing (requests device pair code from gateway)
- GET  /api/v1/pair/status — Desktop polls pairing status (returns license_key when matched)
- POST /api/v1/pair/activate — Desktop activates with obtained license_key, writes to .env

Flow (one-click install):
1. User runs `curl -fsSL https://promiselink.cn/install.sh | bash`
2. Basic edition starts without PRO_LICENSE_KEY → enters pairing mode
3. Desktop calls /pair/init → gets device_pair_code + QR content
4. User scans QR with miniapp (already activated) → miniapp submits to gateway
5. Desktop polls /pair/status → gets license_key when matched
6. Desktop calls /pair/activate → writes license_key to .env, starts WSS relay

License: MPL 2.0
"""

from __future__ import annotations

import os
import pathlib

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from promiselink.config import get_settings
from promiselink.core.logging import get_logger

logger = get_logger("promiselink.pair")

router = APIRouter(prefix="/pair", tags=["pairing"])

_GATEWAY_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class PairInitResponse(BaseModel):
    success: bool
    device_pair_code: str = ""
    qr_content: str = ""
    expires_in: int = 0
    gateway_url: str = ""
    error: str = ""


class PairStatusResponse(BaseModel):
    success: bool
    status: str = "pending"
    license_key: str = ""
    user_id: str = ""
    error: str = ""


class PairActivateRequest(BaseModel):
    license_key: str


class PairActivateResponse(BaseModel):
    success: bool
    message: str = ""
    error: str = ""


def _get_gateway_url() -> str:
    settings = get_settings()
    url = settings.relay_gateway_url or os.environ.get("RELAY_GATEWAY_URL", "https://gateway.promiselink.cn")
    return url.rstrip("/")


def _get_env_path() -> pathlib.Path:
    project_root = pathlib.Path(__file__).resolve().parents[4]
    return project_root / ".env"


@router.post("/init", response_model=PairInitResponse)
async def init_pair() -> PairInitResponse:
    """Initialize device pairing by requesting a code from the gateway.

    Calls the gateway's public POST /api/v1/pair/device endpoint.
    """
    gateway_url = _get_gateway_url()

    try:
        async with httpx.AsyncClient(timeout=_GATEWAY_TIMEOUT) as client:
            response = await client.post(
                f"{gateway_url}/api/v1/pair/device",
                headers={"Content-Type": "application/json"},
            )
    except httpx.HTTPError as exc:
        logger.error("pair_init_network_error", gateway=gateway_url, error=str(exc)[:200])
        return PairInitResponse(
            success=False,
            gateway_url=gateway_url,
            error=f"无法连接网关: {exc}",
        )

    if response.status_code != 200:
        detail = ""
        try:
            detail = response.json().get("error", {}).get("message", "")
        except Exception:
            detail = response.text[:200]
        return PairInitResponse(
            success=False,
            gateway_url=gateway_url,
            error=f"网关返回错误 ({response.status_code}): {detail}",
        )

    data = response.json().get("data", response.json())
    code = data.get("device_pair_code", "")

    # Write pair code to file for background auto-poll task
    if code:
        pair_code_file = pathlib.Path(__file__).resolve().parents[4] / ".pair_code"
        pair_code_file.write_text(code)

    return PairInitResponse(
        success=True,
        device_pair_code=code,
        qr_content=data.get("qr_content", ""),
        expires_in=data.get("expires_in", 300),
        gateway_url=gateway_url,
    )


@router.get("/status", response_model=PairStatusResponse)
async def get_pair_status(code: str) -> PairStatusResponse:
    """Poll the device pairing status from the gateway.

    Query parameter: code — the device_pair_code from /pair/init.
    """
    gateway_url = _get_gateway_url()

    try:
        async with httpx.AsyncClient(timeout=_GATEWAY_TIMEOUT) as client:
            response = await client.get(
                f"{gateway_url}/api/v1/pair/device/{code}",
            )
    except httpx.HTTPError as exc:
        logger.error("pair_status_network_error", error=str(exc)[:200])
        return PairStatusResponse(success=False, error=f"无法连接网关: {exc}")

    if response.status_code != 200:
        return PairStatusResponse(
            success=False,
            error=f"网关返回错误 ({response.status_code})",
        )

    data = response.json().get("data", response.json())
    status = data.get("status", "pending")

    return PairStatusResponse(
        success=True,
        status=status,
        license_key=data.get("license_key") or "",
        user_id=data.get("user_id") or "",
    )


@router.post("/activate", response_model=PairActivateResponse)
async def activate_pair(body: PairActivateRequest, request: Request) -> PairActivateResponse:
    """Activate Pro edition with the obtained license key.

    Writes PRO_LICENSE_KEY to the .env file so it persists across restarts,
    then dynamically starts the WSS relay connection — no restart required.

    2026-07-29 fix: Previously this endpoint only wrote .env and returned
    "即将启动中继服务", but the WSS client was only started in the lifespan
    startup event, so users had to manually restart the basic edition.
    Now we clear the settings cache, reload settings with the new license
    key, and start the WSS client immediately.
    """
    license_key = body.license_key.strip()
    if not license_key:
        return PairActivateResponse(success=False, error="license_key 不能为空")

    env_path = _get_env_path()

    try:
        content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    except OSError as exc:
        logger.error("pair_activate_read_env_failed", path=str(env_path), error=str(exc))
        return PairActivateResponse(success=False, error=f"读取 .env 失败: {exc}")

    lines = content.splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith("PRO_LICENSE_KEY="):
            lines[i] = f"PRO_LICENSE_KEY={license_key}"
            found = True
            break

    if not found:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"PRO_LICENSE_KEY={license_key}")

    new_content = "\n".join(lines) + "\n"

    try:
        env_path.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        logger.error("pair_activate_write_env_failed", path=str(env_path), error=str(exc))
        return PairActivateResponse(success=False, error=f"写入 .env 失败: {exc}")

    os.environ["PRO_LICENSE_KEY"] = license_key

    # Clear the lru_cache on get_settings so the new PRO_LICENSE_KEY is picked up.
    get_settings.cache_clear()
    fresh_settings = get_settings()

    wss_started = False
    wss_error = ""

    # Start WSS relay dynamically if not already running.
    existing_wss = getattr(request.app.state, "relay_wss_client", None)
    if existing_wss is not None:
        # Already running — nothing to do.
        wss_started = True
    elif fresh_settings.relay_gateway_url and fresh_settings.pro_license_key and fresh_settings.relay_wss_enabled:
        try:
            from promiselink.services.relay_wss_client import RelayWSSClient

            relay_wss = RelayWSSClient(
                gateway_url=fresh_settings.relay_gateway_url,
                license_key=fresh_settings.pro_license_key,
                local_api_url=fresh_settings.relay_local_api_url,
                heartbeat_interval=fresh_settings.relay_heartbeat_interval,
                reconnect_interval=fresh_settings.relay_reconnect_interval,
                reconnect_max=fresh_settings.relay_reconnect_max,
                http_request_timeout=fresh_settings.relay_http_request_timeout,
            )
            await relay_wss.start()
            request.app.state.relay_wss_client = relay_wss
            wss_started = True
            logger.info(
                "pair_activate_wss_started",
                gateway=fresh_settings.relay_gateway_url,
                local_api_url=fresh_settings.relay_local_api_url,
            )
        except Exception as exc:
            wss_error = str(exc)[:200]
            logger.error("pair_activate_wss_start_failed", error=wss_error)
    else:
        wss_error = " relay_gateway_url 或 relay_wss_enabled 未配置，无法启动 WSS 中继"

    logger.info("pair_activate_success", license_key=license_key[:10] + "****", wss_started=wss_started)

    if wss_started:
        return PairActivateResponse(
            success=True,
            message="专业版激活成功！中继服务已启动，小程序可连接。",
        )
    return PairActivateResponse(
        success=True,
        message=f"专业版激活成功，但 WSS 中继启动失败（{wss_error}）。请重启基础版后重试。",
        error=wss_error,
    )
