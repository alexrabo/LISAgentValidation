"""Structured JSON request logging middleware — one line per request."""
import json
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("lims.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(json.dumps({
            "method": request.method,
            "path": request.url.path,
            "session_id": request.headers.get("X-Session-ID"),
            "status": response.status_code,
            "duration_ms": duration_ms,
        }))
        return response
