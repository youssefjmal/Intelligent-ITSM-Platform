# Teammate Setup Guide (Docker)

Enterprise onboarding guide for running the Teamwill Intern ITSM Platform locally.

## 1. Purpose
Use this guide to start a complete local stack for demo, QA, and internship handover:
- PostgreSQL
- FastAPI backend
- Next.js frontend

## 2. Prerequisites
- Docker Desktop (with Compose support)
- Git
- Open ports: `3000`, `8000`, `55432`

## 3. Clone Repository
```powershell
git clone https://github.com/youssefjmal/Intelligent-ITSM-Platform
cd jira-ticket-managementv2
```

## 4. Required Local Environment File
Create a root `.env` file before starting compose:

```powershell
@"
JWT_SECRET=replace-with-strong-secret-at-least-32-chars
POSTGRES_PASSWORD=postgres
NEXT_PUBLIC_API_URL=http://localhost:8000/api
"@ | Set-Content .env
```

Minimum requirement:
- `JWT_SECRET` must be set.

## 5. Start Full Stack
```powershell
docker compose up --build
```

Service endpoints:
- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- PostgreSQL host port: `localhost:55432`

## 6. Seed Demo Data (Optional)
```powershell
docker compose exec backend python scripts/seed.py
```

## 7. Default Demo Accounts
- Admin: `admin@teamwill.com` / `admin123`
- Agent: `agent@teamwill.com` / `agent123`
- Viewer: `viewer@teamwill.com` / `viewer123`
- User: `user@teamwill.com` / `user123`

## 8. Operational Commands
Start in background:
```powershell
docker compose up -d
```

Stop:
```powershell
docker compose down
```

Stop and remove volumes:
```powershell
docker compose down -v
```

Rebuild services:
```powershell
docker compose build --no-cache backend frontend
docker compose up
```

Logs:
```powershell
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f db
```

## 9. Validation Checklist
- Frontend loads at `http://localhost:3000`.
- Swagger is available at `http://localhost:8000/docs`.
- Login works with seeded accounts.
- Ticket list and dashboard load without API errors.

## 10. Troubleshooting
- Compose fails on startup: verify root `.env` exists and `JWT_SECRET` is set.
- Backend cannot connect DB: verify `POSTGRES_PASSWORD` consistency.
- Frontend API errors: verify `NEXT_PUBLIC_API_URL` and backend health.

## 11. Security Notes
- Never commit root `.env`.
- Rotate secrets if they were ever exposed in git history.
- Keep integration keys (Jira/SMTP/n8n) only in local or managed secret stores.
