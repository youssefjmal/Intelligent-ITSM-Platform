# Teamwill Intern ITSM Platform

Enterprise documentation for the PFE internship project delivered for Teamwill.

## 1. Executive Summary
This platform is an internal ITSM application designed for Teamwill  operations.
It centralizes ticket intake, triage, resolution tracking, AI-assisted recommendations, and Jira Service Management interoperability.

Business objectives:
- Reduce manual triage effort and improve assignment consistency.
- Give agents and interns actionable AI support from historical incidents (RAG-style retrieval).
- Provide operational visibility through dashboards, SLA insights, and problem management.
- Enable integration-ready workflows with Jira and optional n8n automation.

## 2. Product Scope
In scope:
- Authentication and RBAC (`admin`, `agent`, `viewer`, `user`).
- Ticket lifecycle management (create, triage, update, resolve, close).
- AI support endpoints (classification, recommendations, chat assist).
- Problem management for recurring incidents.
- Notifications and recommendation modules.
- Jira inbound/outbound synchronization.

Out of scope:
- Enterprise SSO (SAML/SCIM) beyond current OAuth support.
- Multi-tenant isolation.
- Full ITIL process suite beyond current ticket/problem/sla focus.

## 3. Target Users
- Admin: governance, user management, system-wide controls.
- Agent: operational triage, problem handling, SLA follow-up.
- Viewer: read-only visibility for supervision/reporting.
- User/Intern: ticket creation and status follow-up.

## 4. Architecture Overview
```text
[Next.js Frontend]
  - Dashboard, Tickets, Problems, Notifications, Admin, AI Chat
           |
           | HTTP /api
           v
[FastAPI Backend]
  - Routers (thin HTTP layer)
  - Services (business logic)
  - AI orchestration + retrieval
  - Jira integration adapters
           |
           v
[PostgreSQL]

External:
- Jira Service Management (optional but supported)
- n8n workflows (optional automation/orchestration)
- Ollama/LLM endpoint (optional AI inference path)
```

## 5. Key Functional Capabilities
- Ticket management: list, filters, detail, updates, analytics.
- AI classification: priority/category/recommendation suggestions.
- AI chat assistant: operational Q&A and ticket draft support.
- Problem management: recurring-incident grouping, linked ticket actions.
- SLA and performance insights.
- Notification center and preferences.
- Jira webhook + reconcile + outbound push paths.

## 6. Technology Stack
- Backend: FastAPI, SQLAlchemy, Alembic, Pydantic, httpx.
- Frontend: Next.js (App Router), React, Tailwind, shadcn/ui.
- Database: PostgreSQL.
- Auth: JWT (cookies + bearer token flows).
- Optional integrations: Jira API, n8n, SMTP, Ollama.

## 7. Repository Structure
```text
jira-ticket-managementv2/
  backend/                FastAPI API, services, migrations, scripts
  frontend/               Next.js UI application
  docs/                   Setup, scrum, n8n, handover documentation
  docker-compose.yml      Full local stack orchestration
```

## 8. Environment and Secrets
Environment files:
- Backend: `backend/.env` (from `backend/.env.example`)
- Frontend: `frontend/.env.local` (from `frontend/.env.local.example`)
- Optional n8n local env: `docs/n8n/.env`

Security rules:
- Never commit real secrets (`.env`, API tokens, encryption keys).
- Keep only templates/examples in git.
- n8n key templates are documented under `docs/n8n/`.

## 9. Quick Start (Local)
### Backend
```powershell
cd backend
copy .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m alembic -c alembic.ini upgrade head
python scripts\seed.py
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8052
```

### Frontend
```powershell
cd frontend
copy .env.local.example .env.local
npm install
npm run dev
```

### Full stack with Docker Compose
```powershell
# from repository root
# ensure JWT_SECRET is set in local .env first
docker compose up --build
```

## 10. Default Demo Accounts
- Admin: `admin@teamwill.com` / `admin123`
- Agent: `agent@teamwill.com` / `agent123`
- Viewer: `viewer@teamwill.com` / `viewer123`
- User: `user@teamwill.com` / `user123`

## 11. Quality and Verification
Recommended verification after pull:
```powershell
# Backend
cd backend
python -m pip install -r requirements.txt
python -m pytest -q

# Frontend
cd ..\frontend
npm install
npm run build
```

## 12. Operational Notes
- API docs: `http://127.0.0.1:8052/docs`
- Frontend app: `http://localhost:3000`
- Backend service: `http://127.0.0.1:8052`
- Jira and n8n flows are optional and can be enabled progressively.

## 13. Risk and Governance Notes
- JWT secret strength is enforced for production profile.
- CORS/host wildcards are guarded for production.
- Integration credentials (Jira/SMTP) must remain in env-only configuration.

## 14. Documentation Index
- Backend deep-dive: `backend/README.md`
- Frontend deep-dive: `frontend/README.md`
- SLA deep-dive: `docs/SLA_README.md`
- AI handoff brief for ChatGPT/Claude: `docs/AI_HANDOFF_CONTEXT.md`
- Chatbot/backend copilot hardening notes: `docs/CHATBOT_BACKEND_ENHANCEMENTS.md`
  - includes the centralized AI policy layout (`taxonomy.py`, `calibration.py`, `conversation_policy.py`, `prompt_policy.py`, `topic_templates.py`) and where to tune thresholds and topic families
- Shared AI resolver workflows and SLA advisory handover: `docs/WORK_RESUME_README.md` (see sections `26.2.1` and `26.3.1`)
- Docker teammate setup: `docs/TEAMMATE_SETUP_README.md`
- n8n workflow guide and setup/checklists: `docs/n8n/README.md`, `docs/n8n/n8n_env_config.md`, `docs/n8n/backend_n8n_integration_checklist.md`
- Scrum artifacts: `docs/scrum/README.md`
- Full technical handover timeline: `docs/WORK_RESUME_README.md`

## 15. Current Mock Data Workflow

For deterministic local demo data and Jira alignment work:

- Local-only reset script: `backend/scripts/reset_local_mock_dataset.py`
- Jira/JSM alignment script: `backend/scripts/sync_local_mock_dataset_to_jira.py`

Notes:
- The reset script is local DB only and avoids Jira/reconcile/network-heavy flows.
- The Jira sync script is destructive for the configured Jira project because it deletes current project issues before recreating the local dataset from the DB.

## 16. Git Safety
Before commit/push:
```powershell
git status --short
git diff --cached --name-only
git diff --cached --name-only | rg "(^|/)\.env($|\.)"
```
