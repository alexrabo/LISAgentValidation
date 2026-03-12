"""
Token bucket rate limiter keyed by X-Session-ID.
In-memory for demo — Redis-backed in production (interface unchanged).
Default: 60 requests/minute per session (configurable via THROTTLE_RPM).
"""
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class _TokenBucket:
    """Token bucket for a single client. Refills at rate tokens/second."""

    def __init__(self, requests_per_minute: int):
        self._capacity = requests_per_minute
        self._tokens = float(requests_per_minute)
        self._rate = requests_per_minute / 60.0  # tokens per second
        self._last_refill = time.monotonic()

    def consume(self) -> bool:
        """Attempt to consume one token. Returns True if allowed."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class ThrottlingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self._buckets: dict[str, _TokenBucket] = {}
        self._rpm = requests_per_minute

    async def dispatch(self, request: Request, call_next) -> Response:
        client = request.headers.get("X-Session-ID") or (
            request.client.host if request.client else "unknown"
        )
        bucket = self._buckets.setdefault(client, _TokenBucket(self._rpm))
        if not bucket.consume():
            return JSONResponse(
                {"error": "Rate limit exceeded", "code": "THROTTLED"},
                status_code=429,
            )
        return await call_next(request)
