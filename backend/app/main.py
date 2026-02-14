
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.exceptions import ITSMGatekeeperException
from app.routers import ai, assignees, auth, emails, integrations_jira, problems, recommendations, tickets, users


def create_app() -> FastAPI:
    setup_logging(settings.LOG_LEVEL)
    app = FastAPI(title=settings.APP_NAME)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(users.router, prefix="/api/users", tags=["users"])
    app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])
    app.include_router(emails.router, prefix="/api/emails", tags=["emails"])
    app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
    app.include_router(recommendations.router, prefix="/api/recommendations", tags=["recommendations"])
    app.include_router(problems.router, prefix="/api", tags=["problems"])
    app.include_router(assignees.router, prefix="/api", tags=["assignees"])
    app.include_router(integrations_jira.router, prefix="/api", tags=["integrations-jira"])

    @app.exception_handler(ITSMGatekeeperException)
    async def handle_itsm_exception(_: Request, exc: ITSMGatekeeperException) -> JSONResponse:
        headers = exc.headers if getattr(exc, "headers", None) else None
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict(), headers=headers)

    return app


app = create_app()
