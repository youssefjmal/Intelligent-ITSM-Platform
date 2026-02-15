# ITSM AI Platform - Intelligent IT Service Management with AI & Automation

## Project Overview
Modern IT Service Desks face escalating ticket volumes, complex technical issues, and increasing user expectations. Manual ticket triage, misrouting, and knowledge fragmentation lead to extended resolution times, agent burnout, and poor service quality.

This project delivers an intelligent ITSM platform that combines AI-driven classification, workflow orchestration, and Jira Service Management integration to create a self-healing IT service ecosystem. The system automatically categorizes, prioritizes, and routes tickets while providing agents with AI-assisted resolution recommendations.

## System Architecture
```
[Frontend]
Next.js Dashboard
      |
      | HTTP /api
      v
[Backend API - FastAPI]
  Thin Routers + Service Layer
      |
      +--> app/routers/ai.py
      |       -> app/services/ai/orchestrator.py
      |       -> intents.py, analytics_queries.py, formatters.py
      |       -> classifier.py, llm.py, quickfix.py, prompts.py
      |
      +--> app/services/tickets.py
      |       -> best-effort outbound push to Jira
      |
      +--> app/integrations/jira/*
      |       -> inbound webhook/reconcile from Jira or n8n
      |
      +--> app/services/jira_kb.py
              -> JSM comment knowledge for AI (RAG)
      |
      v
[PostgreSQL]

[Jira Service Management] <------> [Backend Integrations API]
                 (direct or via n8n webhooks/cron)
```

## Tech Stack
- Backend: FastAPI, SQLAlchemy, Alembic
- Database: PostgreSQL
- Frontend: Next.js (App Router), React, Tailwind CSS
- Auth: JWT in httpOnly cookies
- Orchestration: n8n (optional for webhook/cron flows)
- Analytics: Power BI (planned)

## Key Features
- User authentication with email verification
- Ticket CRUD, analytics, and insights
- AI assistance endpoints with thin router + modular service architecture
- Jira inbound sync (`/api/integrations/jira/webhook`, `/api/integrations/jira/reconcile`; `/upsert` kept as legacy alias)
- Best-effort Jira outbound push on local ticket creation
- JSM comment-aware AI context (RAG-style knowledge block)
- Recommendations module (DB-backed)
- Admin user management + email logs
- Consistent API errors via custom exceptions

## Detailed Docs
- Backend: `backend/README.md`
- Frontend: `frontend/README.md`

## Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL 15+

## Quick Start (Windows PowerShell)
Backend:
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

Frontend:
```powershell
cd C:\Users\kahla\Downloads\jira-ticket-managementv2\frontend
copy .env.local.example .env.local
npm install
npm run dev
```

## Default Accounts
- Admin: `admin@teamwill.com` / `admin123`
- Agent: `agent@teamwill.com` / `agent123`
- Viewer: `viewer@teamwill.com` / `viewer123`
- Normal user: `user@teamwill.com` / `user123`

## Environment Variables
Backend: `backend/.env`
- `DATABASE_URL`
- `JWT_SECRET`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `COOKIE_NAME`
- `REFRESH_COOKIE_NAME`
- `REFRESH_TOKEN_EXPIRE_DAYS`
- `FRONTEND_BASE_URL`
- `CORS_ORIGINS`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SMTP_TLS`
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `JIRA_PROJECT_KEY`
- `JIRA_SERVICE_DESK_ID`
- `JIRA_AUTO_RECONCILE_ENABLED`
- `JIRA_AUTO_RECONCILE_INTERVAL_SECONDS`
- `JIRA_AUTO_RECONCILE_LOOKBACK_DAYS`
- `JIRA_AUTO_RECONCILE_STARTUP_DELAY_SECONDS`

Frontend: `frontend/.env.local`
- `NEXT_PUBLIC_API_URL`

## Project Structure
```
jira-ticket-managementv2/
  backend/
    app/
      core/
      db/
      models/
      routers/
      schemas/
      services/
        ai/
          orchestrator.py
          intents.py
          analytics_queries.py
          formatters.py
          classifier.py
          llm.py
          prompts.py
          quickfix.py
      integrations/
        jira/
      main.py
    alembic/
      versions/
    scripts/
      seed.py
      init_db.sql
    .env
    .env.example
    alembic.ini
    requirements.txt
  frontend/
    app/
      auth/
      tickets/
      recommendations/
      chat/
      admin/
    components/
      ui/
    hooks/
    lib/
    public/
    styles/
    .env.local
    .env.local.example
    next.config.mjs
    package.json
    tailwind.config.ts
  docs/
    scrum/
      user-stories.md
      product-backlog.md
      sprint-backlog.md
      definition-of-done.md
  README.md
```

## Notes
- Jira Service Management integration is available for inbound sync and outbound best-effort ticket push.
- n8n orchestration is optional (webhooks and scheduled reconciliation).
- Email sending is logged in the DB; configure SMTP to send real emails.

## API Docs
Once the backend is running:
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
