
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.exceptions import ITSMGatekeeperException
from app.core.rate_limit import install_global_rate_limit_middleware
from app.core.security_headers import install_security_headers_middleware
from app.integrations.jira.auto_reconcile import start_jira_auto_reconcile, stop_jira_auto_reconcile
from app.routers import ai, assignees, auth, emails, integrations_jira, notifications, problems, recommendations, sla, tickets, users


def create_app() -> FastAPI:
    setup_logging(settings.LOG_LEVEL)
    settings.validate_runtime_security()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await start_jira_auto_reconcile()
        try:
            yield
        finally:
            await stop_jira_auto_reconcile()

    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_hosts,
    )
    install_global_rate_limit_middleware(app)
    install_security_headers_middleware(app, settings)

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(users.router, prefix="/api/users", tags=["users"])
    app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])
    app.include_router(emails.router, prefix="/api/emails", tags=["emails"])
    app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
    app.include_router(recommendations.router, prefix="/api/recommendations", tags=["recommendations"])
    app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
    app.include_router(problems.router, prefix="/api", tags=["problems"])
    app.include_router(assignees.router, prefix="/api", tags=["assignees"])
    # Jira reverse-sync endpoints (webhook + reconcile).
    app.include_router(integrations_jira.router, prefix="/api", tags=["integrations-jira"])
    app.include_router(sla.router, prefix="/api/sla", tags=["sla"])

    @app.exception_handler(ITSMGatekeeperException)
    async def handle_itsm_exception(_: Request, exc: ITSMGatekeeperException) -> JSONResponse:
        headers = exc.headers if getattr(exc, "headers", None) else None
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict(), headers=headers)

    return app


app = create_app()
