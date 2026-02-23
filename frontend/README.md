# Frontend (Next.js)

## Overview
The frontend is a Next.js App Router application providing the ITSM dashboard, ticket management UI, AI assistant chat, and recommendations view. It consumes the FastAPI backend through a single API base URL.

## Requirements
- Node.js 18+

## Setup (Windows PowerShell)
```powershell
cd C:\Users\kahla\Downloads\jira-ticket-managementv2\frontend
copy .env.local.example .env.local
npm install
npm run dev
```

## Environment Variables
File: `frontend/.env.local`
- `NEXT_PUBLIC_API_URL` (example: `http://localhost:8000/api`)

## Running the App
```powershell
npm run dev
```
- App URL: `http://localhost:3000`

## Routes
- `/` Dashboard and KPIs
- `/tickets` Ticket list
- `/tickets/new` Create ticket
- `/tickets/[id]` Ticket detail
- `/chat` AI assistant
- `/recommendations` Recommendations
- `/admin` Admin user management
- `/auth/login` Login
- `/auth/signup` Signup
- `/auth/signup-success` Signup success
- `/auth/verify` Email verification
- `/auth/forgot-password` Request password reset
- `/auth/reset-password` Set new password from reset link

Login flow note:
- `/auth/login` now supports email auto-signup: if the email does not exist, the backend creates the account and sends verification.

## Data Flow
- API calls use `frontend/lib/api.ts` and `NEXT_PUBLIC_API_URL`.
- Auth state uses cookie-based JWT set by the backend.
- `auth-guard` restricts access by roles and permissions.

## Localization
- Translations live in `frontend/lib/i18n.tsx`.
- UI strings are accessed via `useI18n()`.

## Key Components
- `components/ticket-form.tsx` ticket creation + AI classify
- `components/ticket-table.tsx` list view
- `components/ticket-detail.tsx` detail view
- `components/ticket-chatbot.tsx` AI assistant
- `components/recommendations.tsx` recommendations view
- `components/app-shell.tsx` layout shell
- `components/app-sidebar.tsx` navigation

## Styling
- Tailwind CSS is configured in `tailwind.config.ts`.
- Global styles in `frontend/styles/globals.css` and `frontend/app/globals.css`.
- UI primitives from `components/ui/*` (shadcn/ui).

## Build
```powershell
npm run build
npm run start
```

## Validation Commands
Use this sequence when verifying frontend changes:

```powershell
cd C:\Users\kahla\Downloads\jira-ticket-managementv2\frontend
npm install
npm run build
```

Expected:
- Next.js build completes successfully.
- Routes are generated for dashboard, ticket, problem, auth, admin, and assistant pages.

## Troubleshooting
- If you see 401 errors, confirm backend is running and cookies are allowed.
- If pages are blank, verify `NEXT_PUBLIC_API_URL` points to `/api`.
- If ticket/problem pages fail to load data, confirm backend URL in `.env.local` matches the running API host.

## Safe Commit Practices
- Do not commit `frontend/.env.local`.
- Commit only `frontend/.env.local.example` when env keys change.
- Before pushing:

```powershell
git diff --cached --name-only
git diff --cached --name-only | rg "(^|/)\.env($|\.)"
```
