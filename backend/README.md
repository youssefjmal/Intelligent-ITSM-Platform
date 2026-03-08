# Backend API Documentation (FastAPI)

Backend service for the Teamwill Intern ITSM Platform (PFE internship delivery).

## 1. Service Responsibility
The backend is the system-of-record API for:
- Authentication and authorization.
- Ticket and problem domain operations.
- AI orchestration (classification, chat, recommendation assistance).
- Notifications and recommendation modules.
- Jira/JSM integration endpoints.

## 2. Technical Architecture
```text
Routers (HTTP contracts)
  -> Services (business rules)
     -> Models/Schemas (data contract)
        -> PostgreSQL (state)

Integration adapters:
- Jira inbound webhook/reconcile
- Jira outbound push
- Optional n8n trigger/webhook bridge
- Optional LLM/Ollama endpoint
```

### Core backend folders
- `app/routers/` API route definitions (thin controllers).
- `app/services/` business logic and orchestration.
- `app/services/ai/` chat/classification/retrieval modules.
- `app/models/` SQLAlchemy entities.
- `app/schemas/` request/response contracts.
- `app/integrations/jira/` Jira client + mapping + sync logic.
- `alembic/` migration history.

## 3. Runtime Prerequisites
- Python 3.11+
- PostgreSQL 15+
- Optional: Ollama endpoint for local model inference

## 4. Local Setup (Windows PowerShell)
```powershell
cd backend
copy .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m alembic -c alembic.ini upgrade head
python scripts\seed.py
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API docs after startup:
- Swagger: `http://127.0.0.1:8000/docs`
- OpenAPI: `http://127.0.0.1:8000/openapi.json`

## 5. Environment Configuration
Source file: `backend/.env` (template: `backend/.env.example`)

### Required for minimum run
- `DATABASE_URL`
- `JWT_SECRET`
- `FRONTEND_BASE_URL`
- `CORS_ORIGINS`

### Auth and security
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `COOKIE_NAME`
- `REFRESH_COOKIE_NAME`
- `REFRESH_TOKEN_EXPIRE_DAYS`
- `ALLOWED_HOSTS`

### Email
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SMTP_TLS`
- `PASSWORD_RESET_TOKEN_EXPIRE_HOURS`

### AI runtime
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `AI_SLA_RISK_ENABLED`
- `AI_SLA_RISK_MODE`

### Jira / Integration
- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `JIRA_PROJECT_KEY`
- `JIRA_SERVICE_DESK_ID`
- `JIRA_WEBHOOK_SECRET`
- `JIRA_AUTO_RECONCILE_ENABLED`
- `JIRA_AUTO_RECONCILE_INTERVAL_SECONDS`
- `JIRA_AUTO_RECONCILE_LOOKBACK_DAYS`
- `JIRA_AUTO_RECONCILE_STARTUP_DELAY_SECONDS`

### Automation
- `AUTOMATION_SECRET`
- `N8N_WEBHOOK_BASE_URL`

## 6. Security Model
- JWT auth supports cookie and bearer token flows.
- RBAC roles: `admin`, `agent`, `viewer`, `user`.
- Production guardrails enforce strong JWT secret and restrictive CORS/hosts.
- Secrets are env-only and must never be hardcoded in source or docs.

## 7. API Domain Map
Main route groups:
- `/api/auth/*`
- `/api/users/*`
- `/api/tickets/*`
- `/api/problems/*`
- `/api/ai/*`
- `/api/recommendations/*`
- `/api/notifications/*`
- `/api/sla/*`
- `/api/integrations/jira/*`

## 8. Authentication Flows
Supported flows:
- Register + verify email.
- Email login/logout/refresh.
- Password reset (forgot + reset endpoints).
- OAuth start/callback (Google).
- Access via cookies and token pair endpoints.

## 9. Ticket and Problem Domain
Ticket capabilities:
- Create, list, detail, update, status operations.
- Triage updates and analytics.
- Performance/SLA endpoints.

Problem capabilities:
- Recurring incident grouping.
- Linked ticket visibility and mass resolution support.
- AI suggestion support for RCA/workaround/fix fields.

## 10. AI Module (Operational View)
Modules under `app/services/ai/`:
- `orchestrator.py` routing and response assembly.
- `classifier.py` classification and recommendation logic.
- `retrieval.py` hybrid retrieval (embedding + lexical paths).
- `intents.py`, `analytics_queries.py`, `formatters.py`, `prompts.py`, `llm.py`.

Design behavior:
- Graceful fallback when LLM provider is unavailable.
- Confidence + source metadata included where available.
- RAG context integrates Jira comments and local history paths.

## 11. Jira and n8n Integration
Inbound:
- Webhook endpoint for Jira event ingestion.
- Reconcile endpoint for periodic sync.

Outbound:
- Best-effort issue push/update from local ticket events.

n8n:
- Optional orchestration layer for workflow automation.
- Shared secrets and webhook URLs must be configured via env.

## 12. Database and Migrations
- Alembic manages schema evolution.
- Upgrade:
```powershell
python -m alembic -c alembic.ini upgrade head
```
- Seed demo/test data:
```powershell
python scripts\seed.py
```

## 13. Testing and Validation
```powershell
cd backend
python -m pip install -r requirements.txt
python -m pytest -q
```

Expected:
- Tests pass.
- API boots cleanly with configured environment.

## 14. Error Contract
Errors are returned as structured JSON with message/code/details fields through custom exception handling.
This is intended for predictable frontend and automation integration behavior.

## 15. Operational Troubleshooting
- `401/403`: verify auth cookies/tokens and role permissions.
- DB startup failures: verify `DATABASE_URL` and migration state.
- AI latency spikes: inspect retrieval and LLM dependency health.
- Jira sync failures: verify Jira credentials and webhook signature config.
- Email issues: verify SMTP host/port/user/password and TLS settings.

## 16. Production Readiness Checklist
- Strong `JWT_SECRET` configured.
- Explicit `CORS_ORIGINS` and `ALLOWED_HOSTS`.
- Secret values present only in secure env stores.
- Database backups and migration rollback plan.
- Monitoring/alerting integrated for API and DB.

## 17. Safe Commit Rules
- Never commit `backend/.env`.
- Commit only template updates in `.env.example`.
- Validate staged files for secret leakage before push.

```powershell
git diff --cached --name-only
git diff --cached --name-only | rg "(^|/)\.env($|\.)"
```
