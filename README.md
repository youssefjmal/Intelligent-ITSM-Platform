# ITSM AI Platform - Intelligent IT Service Management with AI & Automation

## Project Overview
### The Challenge
Modern IT Service Desks face escalating ticket volumes, complex technical issues, and increasing user expectations. Manual ticket triage, misrouting, and knowledge fragmentation lead to extended resolution times, agent burnout, and poor service quality.

### Our Solution
An intelligent ITSM platform that combines AI-driven classification, n8n workflow automation, and Jira Service Management integration to create a self-healing IT service ecosystem. The system automatically categorizes, prioritizes, and routes tickets while providing agents with AI-assisted resolution recommendations.

## System Architecture
### Core Components
- JSM data ingestion and normalization
- Workflow orchestration with n8n
- AI modules for classification, summarization, and recommendations
- PostgreSQL storage for operational data
- Analytics and dashboards for ITSM KPIs

## Tech Stack
- Backend: FastAPI, SQLAlchemy, Alembic
- Database: PostgreSQL
- Frontend: Next.js (App Router), React, Tailwind CSS
- Auth: JWT stored in httpOnly cookies

## Key Features
- User authentication with email verification
- Ticket CRUD, analytics, and insights
- AI assistance endpoints (rule-based for now)
- Recommendations module (DB-backed)
- Admin user management + email logs

## Project Structure
```text
jira-ticket-managementv2/
  backend/
    app/
      main.py
      routers/
      services/
      models/
      schemas/
    alembic/
    scripts/seed.py
  frontend/
    app/
    components/
    lib/
```

## Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL 15+

## Backend Setup (Windows PowerShell)
1. Create a database named `jira_tickets` in PostgreSQL.
2. Create the backend env file.
3. Install dependencies and run migrations.

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

## Frontend Setup
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

Frontend: `frontend/.env.local`
- `NEXT_PUBLIC_API_URL`

## Notes
- Ollama integration is intentionally not implemented yet.
- Jira Service Management integration is not implemented yet.
- Email sending is logged in the DB for local development.

## API Docs
Once the backend is running:
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
