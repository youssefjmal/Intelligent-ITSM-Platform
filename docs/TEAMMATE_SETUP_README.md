# Teammate Setup Guide (Docker)

This guide lets a teammate run the full app (PostgreSQL + FastAPI + Next.js) with Docker.

## Prerequisites
- Docker Desktop (with Docker Compose)
- Git

## 1) Clone and open the project
```powershell
git clone <your-repo-url>
cd jira-ticket-managementv2
```

## 2) Start everything
```powershell
docker compose up --build
```

Services:
- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- Postgres host port: `localhost:55432`

## 3) Optional: seed demo data
Run this once (or whenever you want to reseed):
```powershell
docker compose exec backend python scripts/seed.py
```

## Default accounts
- Admin: `admin@teamwill.com` / `admin123`
- Agent: `agent@teamwill.com` / `agent123`
- Viewer: `viewer@teamwill.com` / `viewer123`
- User: `user@teamwill.com` / `user123`

## Common commands

Start in background:
```powershell
docker compose up -d
```

Stop:
```powershell
docker compose down
```

Stop and remove DB data:
```powershell
docker compose down -v
```

View logs:
```powershell
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f db
```

Rebuild after dependency changes:
```powershell
docker compose build --no-cache backend frontend
docker compose up
```

## Notes
- Backend runs Alembic migrations automatically at startup.
- Frontend hot reload works from your local files.
- Verification links/codes are sent by email only (not returned by API/UI).
