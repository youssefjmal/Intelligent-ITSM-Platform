
from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.exceptions import ITSMGatekeeperException
from app.core.rate_limit import install_global_rate_limit_middleware
from app.core.security_headers import install_security_headers_middleware
from app.integrations.jira.auto_reconcile import start_jira_auto_reconcile, stop_jira_auto_reconcile
from app.core import cache as _cache_module
from app.routers import ai, assignees, auth, emails, integrations_jira, notifications, problems, recommendations, sla, tickets, translations, users
from app.routers import search as search_router
from app.routers import security as security_router

logger = logging.getLogger(__name__)


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
        # ISO 27001 A.12.4 — enforce audit log retention on startup
        try:
            from app.db.session import SessionLocal
            from app.services.audit_purge import purge_old_audit_events
            with SessionLocal() as _db:
                purge_old_audit_events(_db)
        except Exception as _purge_exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("Audit purge failed on startup: %s", _purge_exc)
        await start_jira_auto_reconcile()
        # Pre-warm off-topic anchor embeddings so the first chat request
        # doesn't pay the full cold-cache penalty (8–22 s for 28 Ollama calls).
        try:
            import asyncio
            from app.services.ai.conversation_policy import ITSM_ANCHOR_PHRASES
            from app.services.embeddings import compute_embedding

            async def _prewarm():
                for phrase in ITSM_ANCHOR_PHRASES:
                    try:
                        await asyncio.to_thread(compute_embedding, phrase)
                    except Exception:
                        break  # Ollama not ready yet; skip silently

            asyncio.ensure_future(_prewarm())
        except Exception as _pw_exc:  # noqa: BLE001
            logger.debug("Anchor pre-warm skipped: %s", _pw_exc)
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
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "Cookie", "X-Requested-With"],
    )
    if settings.ENV != "development":
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
    app.include_router(security_router.router, prefix="/api/admin", tags=["security-audit"])

    @app.exception_handler(ITSMGatekeeperException)
    async def handle_itsm_exception(_: Request, exc: ITSMGatekeeperException) -> JSONResponse:
        headers = exc.headers if getattr(exc, "headers", None) else None
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict(), headers=headers)

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        if not settings.PROMETHEUS_METRICS_ENABLED:
            raise HTTPException(status_code=404, detail="Not Found")

        if not settings.PROMETHEUS_METRICS_TOKEN.strip():
            logger.warning("Metrics endpoint requested while PROMETHEUS_METRICS_TOKEN is unset.")
            raise HTTPException(status_code=503, detail="metrics_misconfigured")

        authorization = request.headers.get("Authorization", "").strip()
        token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
        if not settings.prometheus_metrics_token_matches(token):
            raise HTTPException(status_code=401, detail="unauthorized")

        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()

# ── Prometheus HTTP metrics ────────────────────────────────────────────────

Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/metrics"],
).instrument(app)
