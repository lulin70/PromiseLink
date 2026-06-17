"""Audit logging middleware.

Logs request metadata (not body content) for audit purposes.
Records: request_id, user_id, method, path, status_code, duration_ms, ip.

Reference: Pro_Edition_Tech_Design_Phase0.md §9.5, §9.3 (data minimization)
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("gateway.audit")


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Log request metadata for audit purposes.

    IMPORTANT: Per §9.3 data minimization, this middleware NEVER logs
    request/response body content. Only metadata is recorded.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.time()
        response = await call_next(request)
        duration_ms = int((time.time() - start_time) * 1000)

        # Extract metadata (no body content!)
        audit_data = {
            "request_id": getattr(request.state, "request_id", ""),
            "user_id": getattr(request.state, "user_id", ""),
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client_ip": request.client.host if request.client else "",
        }

        # Log as structured JSON
        logger.info("audit_log", extra=audit_data)

        return response
