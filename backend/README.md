# Backend API (FastAPI)

## Overview
This backend provides authentication, ticket management, analytics, AI-assisted classification/chat, and recommendations. It exposes a REST API used by the Next.js frontend and stores data in PostgreSQL.

## Requirements
- Python 3.11+
- PostgreSQL 15+

## Setup (Windows PowerShell)
```powershell
cd C:\Users\kahla\Downloads\jira-ticket-managementv2\backend
copy .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m alembic -c alembic.ini upgrade head
python scripts\seed.py
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Environment Variables
File: `backend/.env`
- `ENV` (default: development)
- `DATABASE_URL` (PostgreSQL connection string)
- `JWT_SECRET` (JWT signing secret)
- `LOG_LEVEL` (INFO, DEBUG, etc.)
- `FRONTEND_BASE_URL` (used for emails)
- `CORS_ORIGINS` (comma-separated)
- `OLLAMA_BASE_URL` (optional local LLM)
- `OLLAMA_MODEL` (optional local LLM)
- `JIRA_BASE_URL` (planned Jira integration)
- `JIRA_EMAIL` (planned Jira integration)
- `JIRA_API_TOKEN` (planned Jira integration)
- `JIRA_PROJECT_KEY` (planned Jira integration)
- `JIRA_SERVICE_DESK_ID` (planned Jira integration)

## Database and Migrations
- Migrations are managed by Alembic.
- Run migrations:
```powershell
python -m alembic -c alembic.ini upgrade head
```
- Seed data (users, tickets, recommendations):
```powershell
python scripts\seed.py
```

## Running the API
```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
- Base URL: `http://127.0.0.1:8000`
- Swagger UI: `http://127.0.0.1:8000/docs`

## Authentication Flow
- `POST /api/auth/register` creates a user and returns a verification token (dev only).
- `POST /api/auth/verify` verifies email using token.
- `POST /api/auth/login` sets a JWT cookie.
- `POST /api/auth/logout` clears the cookie.
- Most endpoints require authentication via cookie.

## API Routes (Summary)
- Auth: `/api/auth/*`
- Users: `/api/users/*`
- Tickets: `/api/tickets/*`
- AI: `/api/ai/*`
- Recommendations: `/api/recommendations/*`
- Emails: `/api/emails/*`
- Assignees: `/api/assignees`

## Error Handling
Custom exceptions are returned as consistent JSON:
```json
{
  "error": "SomeException",
  "message": "...",
  "error_code": "...",
  "details": { "...": "..." }
}
```
Examples:
- `AuthenticationException`
- `NotFoundError`
- `ConflictError`
- `BadRequestError`

## AI Features
- `POST /api/ai/classify` returns priority, category, and recommendations.
- `POST /api/ai/chat` returns a reply and optionally a ticket draft.
- If Ollama is unavailable, the system falls back to rule-based logic.

## Recommendations Module
- Stored in `recommendations` table.
- Seeded with examples by default.
- Exposed via `GET /api/recommendations`.

## Folder Layout
- `app/core` config, logging, security, custom exceptions, deps.
- `app/db` SQLAlchemy session and base.
- `app/models` ORM models.
- `app/schemas` Pydantic request/response models.
- `app/services` business logic.
- `app/routers` API endpoints.
- `alembic` migrations.
- `scripts` local utilities and seed data.

## Troubleshooting
- Ensure PostgreSQL is running and `DATABASE_URL` is correct.
- If auth fails, verify cookies are not blocked and `JWT_SECRET` is set.
- If AI fails, check `OLLAMA_BASE_URL` or rely on rule-based fallback.
