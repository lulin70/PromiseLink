"""FastAPI dependency injection for rate limiting and other shared concerns."""

import ipaddress

from fastapi import Depends, Request

from promiselink.config import get_settings
from promiselink.core.auth import get_optional_user_id
from promiselink.core.exceptions import BusinessError
from promiselink.core.logging import get_logger
from promiselink.core.rate_limiter import check_rate_limit

logger = get_logger("promiselink.dependencies")

# Lazy-initialized compiled trusted proxy list (settings load once at startup)
_trusted_exact_ips: set[str] | None = None
_trusted_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None = None


def _init_trusted_proxies() -> None:
    """Compile trusted_proxies config into exact IPs and CIDR networks (once)."""
    global _trusted_exact_ips, _trusted_networks
    if _trusted_exact_ips is not None:
        return
    _trusted_exact_ips = set()
    _trusted_networks = []
    for entry in get_settings().trusted_proxies:
        if entry == "*":
            _trusted_exact_ips.add("*")
        elif "/" in entry:
            try:
                _trusted_networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                logger.warning("invalid_trusted_proxy_cidr", entry=entry)
        else:
            _trusted_exact_ips.add(entry)


def _is_trusted_proxy(direct_ip: str) -> bool:
    """Check if direct_ip is a trusted proxy (exact match, CIDR, or wildcard)."""
    if not get_settings().trusted_proxies:
        return False
    _init_trusted_proxies()
    assert _trusted_exact_ips is not None and _trusted_networks is not None
    if "*" in _trusted_exact_ips:
        return True
    if direct_ip in _trusted_exact_ips:
        return True
    try:
        ip = ipaddress.ip_address(direct_ip)
        return any(ip in net for net in _trusted_networks)
    except ValueError:
        return False


def _get_client_ip(request: Request) -> str:
    """Extract real client IP from request, honoring X-Forwarded-For from trusted proxies."""
    direct_ip = request.client.host if request.client else "unknown"
    if _is_trusted_proxy(direct_ip):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return direct_ip


async def rate_limit_dependency(
    request: Request,
    user_id: str | None = Depends(get_optional_user_id),
) -> None:
    """Standard rate limit dependency for general API endpoints.

    Uses authenticated user limit when a valid JWT is present,
    otherwise falls back to the unauthenticated limit.
    """
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return

    if user_id:
        key = f"user:{user_id}"
        limit = settings.rate_limit_authenticated
    else:
        client_ip = _get_client_ip(request)
        key = f"ip:{client_ip}"
        limit = settings.rate_limit_unauthenticated

    allowed, remaining, retry_after = await check_rate_limit(key, limit)

    if not allowed:
        raise BusinessError(
            "Rate limit exceeded",
            code="RATE_LIMITED",
            details={"retry_after": int(retry_after) + 1},
        )


async def rate_limit_llm_dependency(
    request: Request,
    user_id: str | None = Depends(get_optional_user_id),
) -> None:
    """Rate limit dependency for LLM-heavy endpoints (/voice/, /media/).

    Uses a lower limit than standard endpoints to protect LLM API quotas.
    """
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return

    if user_id:
        key = f"llm:user:{user_id}"
    else:
        client_ip = _get_client_ip(request)
        key = f"llm:ip:{client_ip}"

    limit = settings.rate_limit_llm

    allowed, remaining, retry_after = await check_rate_limit(key, limit)

    if not allowed:
        raise BusinessError(
            "Rate limit exceeded for LLM endpoint",
            code="RATE_LIMITED",
            details={"retry_after": int(retry_after) + 1},
        )
