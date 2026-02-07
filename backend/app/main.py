"""FastAPI application entrypoint and router registration."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import ai, auth, emails, tickets, users, recommendations, assignees


def create_app() -> FastAPI:
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
    app.include_router(assignees.router, prefix="/api", tags=["assignees"])
    return app


app = create_app()
