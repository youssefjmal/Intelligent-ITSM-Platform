# Frontend Documentation (Next.js)

Frontend UI for the Teamwill Intern ITSM Platform (PFE internship project).

## 1. Purpose
The frontend provides the operational interface for:
- Ticket lifecycle management.
- AI-assisted triage and support interactions.
- Problem monitoring and recurring incident analysis.
- Notifications and admin controls.

## 2. Technology
- Next.js (App Router)
- React + TypeScript
- Tailwind CSS
- shadcn/ui component primitives

## 3. User-Facing Modules
Primary routes:
- `/` dashboard and KPI overview
- `/tickets` list and filterable grid
- `/tickets/new` ticket creation + AI classify
- `/tickets/[id]` ticket detail and actions
- `/problems` recurring problem list
- `/problems/[id]` problem detail + AI suggestions
- `/chat` AI assistant
- `/recommendations` recommendation views
- `/notifications` notification center
- `/admin` admin panel (role-gated)
- `/auth/*` authentication and recovery flows

## 4. Access and Roles
The UI enforces backend-authenticated session behavior and permission checks through auth guard components.
Role-sensitive actions are hidden or disabled when user permissions do not allow mutation.

## 5. Runtime Configuration
Environment file: `frontend/.env.local`

Required variable:
- `NEXT_PUBLIC_API_URL` (example: `http://localhost:8052/api`)

Template file:
- `frontend/.env.local.example`

## 6. Local Setup (Windows PowerShell)
```powershell
cd frontend
copy .env.local.example .env.local
npm install
npm run dev
```

App URL:
- `http://localhost:3000`

## 7. Build and Validation
```powershell
cd frontend
npm install
npm run build
```

Expected:
- Production build succeeds.
- Route compilation completes without runtime import errors.

## 8. Frontend Architecture Notes
- API access is centralized in `frontend/lib/api.ts`.
- Domain client helpers are split into dedicated modules (`tickets-api.ts`, `problems-api.ts`, `notifications-api.ts`, etc.).
- Localization strings are maintained in `frontend/lib/i18n.tsx`.
- Shared layout and navigation live in `components/app-shell.tsx` and `components/app-sidebar.tsx`.

## 9. Styling and UI System
- Tailwind config: `tailwind.config.ts`
- Global styles: `app/globals.css`, `styles/globals.css`
- Reusable UI primitives: `components/ui/*`

## 10. Security and Data Handling
- No secret should exist in frontend source.
- Only public config variables (`NEXT_PUBLIC_*`) are allowed client-side.
- Auth relies on secure backend cookies/tokens; frontend does not store privileged secrets.

## 11. Troubleshooting
- API 401/403: verify backend is running and authentication state is valid.
- Missing data: verify `NEXT_PUBLIC_API_URL` target and backend health.
- Build errors: clear local caches and reinstall dependencies.

## 12. Commit Hygiene
- Never commit `frontend/.env.local`.
- Commit only `frontend/.env.local.example` when config keys change.

```powershell
git diff --cached --name-only
git diff --cached --name-only | rg "(^|/)\.env($|\.)"
```
