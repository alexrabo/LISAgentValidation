"""
OpenID Connect authentication middleware.

STUB for March 19 — passthrough when OPENID_ENABLED=false (default).
Production: validate bearer token against OIDC provider
(GCP Identity Platform, Auth0, Azure AD — no code change required,
only OPENID_ISSUER + OPENID_AUDIENCE env vars needed).

The /health endpoint is always exempt.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from settings import settings

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class OpenIDMiddleware(BaseHTTPMiddleware):
    EXEMPT_PATHS = {"/health"}

    async def dispatch(self, request: Request, call_next) -> Response:
        if not settings.openid_enabled or request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        token = (
            request.headers.get("Authorization", "")
            .removeprefix("Bearer ")
            .strip()
        )
        if not token:
            return JSONResponse(
                {"error": "Unauthorized", "code": "MISSING_TOKEN"},
                status_code=401,
            )
        # STUB: decode + verify against OPENID_ISSUER jwks_uri
        # Production: use python-jose or authlib to validate JWT
        return await call_next(request)
