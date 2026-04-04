
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
from app.core import cache as _cache_module
from app.routers import ai, assignees, auth, emails, integrations_jira, notifications, problems, recommendations, sla, tickets, translations, users
from app.routers import search as search_router


def create_app() -> FastAPI:
    setup_logging(settings.LOG_LEVEL)
    settings.validate_runtime_security()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Increase the default thread pool so long LLM/RAG calls don't starve
        # other sync endpoints waiting for a thread slot (default is cpu_count+4).
        import anyio.to_thread
        anyio.to_thread.current_default_thread_limiter().total_tokens = 60
        _cache_module._get_client()  # warm up Redis; logs warning if unavailable
        await start_jira_auto_reconcile()
        # Start proactive SLA monitor background task
        try:
            from app.services.sla.sla_monitor import start_sla_monitor, stop_sla_monitor
            await start_sla_monitor()
        except Exception as _sla_exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("SLA monitor failed to start: %s", _sla_exc)
        try:
            yield
        finally:
            _cache_module.close()
            await stop_jira_auto_reconcile()
            try:
                from app.services.sla.sla_monitor import stop_sla_monitor
                await stop_sla_monitor()
            except Exception:  # noqa: BLE001
                pass

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
    app.include_router(translations.router, prefix="/api/translations", tags=["translations"])
    app.include_router(recommendations.router, prefix="/api/recommendations", tags=["recommendations"])
    app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
    app.include_router(problems.router, prefix="/api", tags=["problems"])
    app.include_router(assignees.router, prefix="/api", tags=["assignees"])
    # Jira reverse-sync endpoints (webhook + reconcile).
    app.include_router(integrations_jira.router, prefix="/api", tags=["integrations-jira"])
    app.include_router(sla.router, prefix="/api/sla", tags=["sla"])
    app.include_router(search_router.router, prefix="/api", tags=["search"])

    @app.exception_handler(ITSMGatekeeperException)
    async def handle_itsm_exception(_: Request, exc: ITSMGatekeeperException) -> JSONResponse:
        headers = exc.headers if getattr(exc, "headers", None) else None
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict(), headers=headers)

    return app


app = create_app()
