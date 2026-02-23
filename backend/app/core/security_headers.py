"""HTTP security headers middleware."""

from __future__ import annotations

from fastapi import FastAPI, Request

from app.core.config import Settings


def install_security_headers_middleware(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)

        path = request.url.path or ""
        if path.startswith("/api"):
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
            response.headers["Cross-Origin-Resource-Policy"] = "same-site"
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            if settings.is_production:
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response
