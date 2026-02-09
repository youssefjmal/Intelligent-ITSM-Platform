# ITSM AI Platform - Intelligent IT Service Management with AI & Automation

## Project Overview
Modern IT Service Desks face escalating ticket volumes, complex technical issues, and increasing user expectations. Manual ticket triage, misrouting, and knowledge fragmentation lead to extended resolution times, agent burnout, and poor service quality.

This project delivers an intelligent ITSM platform that combines AI-driven classification, workflow orchestration, and Jira Service Management integration to create a self-healing IT service ecosystem. The system automatically categorizes, prioritizes, and routes tickets while providing agents with AI-assisted resolution recommendations.

## System Architecture
```
[Jira Service Management]
          |
          | REST API (planned)
          v
        [n8n]
          |
          | Triggers / Webhooks
          v
       [Backend API]
  FastAPI + Postgres
          |
          v
      [Frontend]
 Next.js Dashboard
```

## Tech Stack
- Backend: FastAPI, SQLAlchemy, Alembic
- Database: PostgreSQL
- Frontend: Next.js (App Router), React, Tailwind CSS
- Auth: JWT in httpOnly cookies
- Orchestration: n8n (planned)
- Analytics: Power BI (planned)

## Key Features
- User authentication with email verification
- Ticket CRUD, analytics, and insights
- AI assistance endpoints (rule-based fallback, optional Ollama)
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
- `FRONTEND_BASE_URL`
- `CORS_ORIGINS`
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `JIRA_PROJECT_KEY`
- `JIRA_SERVICE_DESK_ID`

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
  README.md
```

## Notes
- Jira Service Management integration is not implemented yet.
- n8n orchestration is planned (webhooks and escalation workflows).
- Email sending is logged in the DB for local development.

## API Docs
Once the backend is running:
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
