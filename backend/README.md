# Backend API (FastAPI)

## Overview
This backend provides authentication, ticket management, analytics, AI-assisted classification/chat, and recommendations. It exposes a REST API used by the Next.js frontend and stores data in PostgreSQL.

## Architecture (Current)
```
app/routers/* (HTTP layer)
   |
   +--> routers/ai.py (thin)
   |      -> services/ai/orchestrator.py
   |      -> services/ai/intents.py
   |      -> services/ai/analytics_queries.py
   |      -> services/ai/formatters.py
   |
   +--> routers/tickets.py
   |      -> services/tickets.py
   |      -> integrations/jira/outbound.py (best-effort Jira push)
   |
   +--> routers/integrations_jira.py
          -> integrations/jira/service.py (upsert/reconcile)

services/jira_kb.py provides JSM comment knowledge blocks for AI prompts.
```

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
- `ACCESS_TOKEN_EXPIRE_MINUTES` (access token lifetime)
- `COOKIE_NAME` (access token cookie name)
- `REFRESH_COOKIE_NAME` (refresh token cookie name)
- `REFRESH_TOKEN_EXPIRE_DAYS` (refresh token lifetime)
- `LOG_LEVEL` (INFO, DEBUG, etc.)
- `FRONTEND_BASE_URL` (used for emails)
- `CORS_ORIGINS` (comma-separated)
- `SMTP_HOST` (SMTP server host; leave empty to disable sending)
- `SMTP_PORT` (SMTP server port)
- `SMTP_USER` (SMTP username)
- `SMTP_PASSWORD` (SMTP password)
- `SMTP_FROM` (from address)
- `SMTP_TLS` (true/false)
- `PASSWORD_RESET_TOKEN_EXPIRE_HOURS` (reset link expiration)
- `GOOGLE_CLIENT_ID` (Google OAuth web client ID)
- `GOOGLE_CLIENT_SECRET` (Google OAuth web client secret)
- `GOOGLE_REDIRECT_URI` (default: `http://localhost:8000/api/auth/google/callback`)
- `OLLAMA_BASE_URL` (optional local LLM)
- `OLLAMA_MODEL` (optional local LLM)
- `JIRA_BASE_URL` (Jira base URL used by sync/import/outbound)
- `JIRA_EMAIL` (Jira technical user email)
- `JIRA_API_TOKEN` (Jira API token)
- `JIRA_PROJECT_KEY` (preferred Jira project key)
- `JIRA_SERVICE_DESK_ID` (service desk id used by import flows)
- `JIRA_KB_ENABLED` (enable JSM comment knowledge for AI prompts)
- `JIRA_KB_MAX_ISSUES` (number of Jira issues scanned for comments)
- `JIRA_KB_MAX_COMMENTS_PER_ISSUE` (latest comments kept per issue)
- `JIRA_KB_TOP_MATCHES` (top relevant comments injected into prompt)
- `JIRA_KB_CACHE_SECONDS` (cache TTL for fetched Jira comments)
- `JIRA_SYNC_PAGE_SIZE` (reconcile page size for Jira reverse sync)
- `JIRA_WEBHOOK_SECRET` (optional HMAC secret for Jira/n8n webhook signature)
- `JIRA_AUTO_RECONCILE_ENABLED` (run background Jira pull loop at API startup)
- `JIRA_AUTO_RECONCILE_INTERVAL_SECONDS` (seconds between background reconcile runs)
- `JIRA_AUTO_RECONCILE_LOOKBACK_DAYS` (fallback lookback if no sync state exists yet)
- `JIRA_AUTO_RECONCILE_STARTUP_DELAY_SECONDS` (initial delay before first background reconcile)

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
- Bulk import local tickets/comments into Jira (dry-run first):
```powershell
python scripts\jira_bulk_import.py --limit 80
python scripts\jira_bulk_import.py --limit 80 --apply
```
- For JSM request types exposing `Urgency` and `Impact`, these fields are auto-filled from local ticket priority during import.
- Importer also syncs local admin/agent users to Jira and auto-assigns issues by Jira `accountId` when possible.
- Existing imported issues can be updated in place (description cleanup + assignee + urgency/impact) with:
```powershell
python scripts\jira_bulk_import.py --apply --skip-existing --update-existing
```

## Running the API
```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
- Base URL: `http://127.0.0.1:8000`
- Swagger UI: `http://127.0.0.1:8000/docs`

## Authentication Flow
- `POST /api/auth/register` creates a user and returns a verification token (dev only).
- `POST /api/auth/email-login` logs in verified users, and auto-creates + sends verification for unknown emails.
- `POST /api/auth/forgot-password` sends a password reset link by email.
- `POST /api/auth/reset-password` updates password using a reset token.
- `POST /api/auth/verify` verifies email using token.
- `POST /api/auth/verify-code` verifies email using `email + 6-digit code`.
- `GET /api/auth/google/start` starts Google OAuth login/signup.
- `GET /api/auth/google/callback` handles Google OAuth callback and signs user in.
- `POST /api/auth/login` sets a JWT cookie.
- `POST /api/auth/refresh` rotates refresh token and renews access cookie.
- `POST /api/auth/logout` clears the cookie.
- `POST /api/auth/token` returns bearer access + refresh tokens (non-cookie clients).
- `POST /api/auth/token/refresh` rotates bearer refresh token and returns a new token pair.
- Most endpoints accept either access cookie or `Authorization: Bearer <access_token>`.

## API Routes (Summary)
- Auth: `/api/auth/*`
- Users: `/api/users/*`
- Tickets: `/api/tickets/*`
- SLA: `/api/sla/*`
- AI: `/api/ai/*`
- Recommendations: `/api/recommendations/*`
- Notifications: `/api/notifications/*`
- Emails: `/api/emails/*`
- Assignees: `/api/assignees`
- Integrations: `/api/integrations/jira/*`

## Validation Commands
Use these commands to confirm backend integrity after changes:

```powershell
cd C:\Users\kahla\Downloads\jira-ticket-managementv2\backend
python -m pip install -r requirements.txt
python -m pytest -q
```

Expected:
- All tests pass.
- No import errors for optional integrations declared in `requirements.txt`.

## n8n Reverse Sync (Jira -> Backend)
- n8n is the orchestrator only; source of truth remains Jira.
- Backend mirrors Jira into Postgres and keeps AI enrichments locally.

### Workflow A: Webhook push (near real-time)
1. Jira Webhook Trigger in n8n (issue created/updated).
2. HTTP Request node:
   - Method: `POST`
   - URL: `http://127.0.0.1:8000/api/integrations/jira/webhook` (`/upsert` is kept as a legacy alias)
   - Headers:
     - `Content-Type: application/json`
     - `X-Jira-Webhook-Secret: <raw shared secret>` or
     - `X-Signature: <sha256 hex or sha256=<hex>>` (if `JIRA_WEBHOOK_SECRET` set)
     - `X-Sync-Origin: n8n`
   - Body: raw Jira webhook JSON, or simplified:
```json
{
  "issueKey": "ITSM-123",
  "fields": {
    "summary": "VPN outage",
    "status": { "name": "In Progress", "statusCategory": { "key": "indeterminate" } },
    "priority": { "name": "High" },
    "issuetype": { "name": "Incident" },
    "labels": ["vpn", "network"],
    "assignee": { "displayName": "Agent One" },
    "reporter": { "displayName": "Reporter One" },
    "created": "2026-02-14T10:00:00.000+0000",
    "updated": "2026-02-14T10:05:00.000+0000"
  }
}
```

### Workflow B: Cron reconciliation (safety net)
1. Cron Trigger every 5-10 minutes.
2. HTTP Request node:
   - Method: `POST`
   - URL: `http://127.0.0.1:8000/api/integrations/jira/reconcile`
   - Body:
```json
{
  "since": "2026-02-14T09:00:00Z",
  "project_key": "ITSM"
}
```
- If `since` is omitted, backend uses stored `jira_sync_state.last_synced_at`.
- Typical response:
```json
{
  "status": "ok",
  "project_key": "ITSM",
  "since": "2026-02-14T09:00:00+00:00",
  "fetched": 25,
  "created": 4,
  "updated": 18,
  "unchanged": 3,
  "errors": []
}
```

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
- AI router is thin: core logic is in `app/services/ai/orchestrator.py`.
- Intent detection, analytics query logic, and formatting are split into:
  - `app/services/ai/intents.py`
  - `app/services/ai/analytics_queries.py`
  - `app/services/ai/formatters.py`
- When Jira credentials are configured, AI context is enriched from existing Jira issue comments.
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
- `app/services/ai` chat/classification orchestration and helpers.
- `app/routers` API endpoints.
- `app/integrations/jira` inbound/outbound Jira integration logic.
- `alembic` migrations.
- `scripts` local utilities and seed data.

## Troubleshooting
- Ensure PostgreSQL is running and `DATABASE_URL` is correct.
- If auth fails, verify cookies are not blocked and `JWT_SECRET` is set.
- If AI fails, check `OLLAMA_BASE_URL` or rely on rule-based fallback.
- If Jira webhook calls are rejected, verify `JIRA_WEBHOOK_SECRET` and incoming headers (`X-Jira-Webhook-Secret` or `X-Signature`).
- If reverse sync returns no results, verify `JIRA_PROJECT_KEY` and the `since` window used by `/api/integrations/jira/reconcile`.

## Safe Commit Practices
- Never commit runtime env files (`backend/.env`).
- Only commit templates (`backend/.env.example`) when variables change.
- Check staged files before pushing:

```powershell
git diff --cached --name-only
git diff --cached --name-only | rg "(^|/)\.env($|\.)"
```

## Intentional Constants
The codebase keeps a small set of fixed constants by design:
- `app/core/ticket_limits.py`: `MAX_TAGS`, `MAX_TAG_LEN` to keep API payloads stable and prevent oversized Jira labels from breaking schemas.
- `app/integrations/jira/service.py`: local seed label prefixes (`twseed_tw_`, `local_tw_`) used to identify import-managed tickets.
- `app/routers/auth.py`: Google OAuth endpoints (official provider URLs) are intentionally fixed.

These are intentional hardcoded values. Environment-specific values (DB, Jira credentials, SMTP, Ollama, JWT secret) must stay in `.env`.
