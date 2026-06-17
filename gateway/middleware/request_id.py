"""Request ID middleware.

Generates a UUID v4 request ID for each request if not provided by the
client. The ID is stored in request.state and returned in the
X-Request-ID response header.

Reference: Pro_Edition_Tech_Design_Phase0.md §4.1.1
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject a request ID into every request and response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Use client-provided ID or generate a new one
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
