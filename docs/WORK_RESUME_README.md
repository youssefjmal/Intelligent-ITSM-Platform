# Full Project Resume (Frontend + Backend + Database + Integrations)

Enterprise audience note:
- This file is the full technical handover ledger for Teamwill stakeholders.
- It is intentionally detailed and chronological (architecture + delivery history + integration status).
- For a concise entry point, start with root `README.md`, then backend/frontend READMEs.

Quick navigation:
1. Scope and objective
2. Architecture and platform design
3. Backend and frontend implementation details
4. Database and migration evolution
5. Jira/n8n/AI integration delivery details
6. Chronological timeline and current release status
7. Current workspace state and handoff priorities (sections 26 to 28)

Current workspace note:
- This file originally tracked the pushed milestones through the February delivery.
- The live workspace now contains additional local work through `2026-03-16`, especially around evidence-first AI recommendations, deterministic SLA advisory, and backend-driven notifications.
- For the fastest current-state ramp-up, read sections `25` through `28` first, then come back to the earlier architecture/history sections if needed.

## 1. Scope of this resume

This document is a full end-to-end resume of the project from initial setup to the latest step, including:

1. Product intent and architecture.
2. Backend system design and APIs.
3. Frontend structure and capabilities.
4. Database model and migration evolution.
5. AI/automation and Jira/n8n integrations.
6. Chronological project timeline from first commit to latest commit.
7. Final status after the most recent push.

---

## 2. Project identity and objective

Project: `ITSM AI Platform - Intelligent IT Service Management with AI & Automation`

Core objective:

- Build an IT service management platform that reduces manual triage effort through AI-assisted ticket classification, routing support, analytics insights, and Jira Service Management integration.

Primary value targets:

1. Faster ticket intake and triage.
2. Better assignment and prioritization consistency.
3. Better visibility into operations through KPIs and performance analytics.
4. Reuse of historical issue knowledge in AI responses.
5. Interoperability with Jira/JSM for inbound and outbound workflows.

---

## 3. High-level architecture

Logical architecture:

1. Frontend:
   - Next.js App Router UI.
   - Calls backend REST APIs.
2. Backend:
   - FastAPI application.
   - Thin router layer + service layer business logic.
   - SQLAlchemy ORM and Alembic migrations.
3. Database:
   - PostgreSQL as system-of-record for local ITSM entities.
4. External systems:
   - Jira Service Management.
   - Optional n8n orchestration layer.
   - Optional Ollama/local LLM inference path.

Transport:

- Frontend <-> Backend via HTTP JSON (`/api/*`).
- Backend <-> Jira via Jira REST v3.
- JWT auth via cookie and token endpoints.

---

## 4. Chronological timeline (from first commit to latest)

Based on repository history:

1. `2026-02-04` `b6ff950` - Initial commit.
2. `2026-02-04` `203c19b` - README revised with project overview.
3. `2026-02-04` `da9da5a` - README cleanup.
4. `2026-02-07` `98202de` - README content normalization.
5. `2026-02-07` `37a0033` - Initial backend + frontend project setup.
6. `2026-02-09` `ba3d9d1` - Early implementation milestone.
7. `2026-02-14` `17885c1` - Auth/AI refactor + Jira reverse sync integration.
8. `2026-02-15` `6fd8cb9` - Problem management workflows + AI confidence + UI updates.
9. `2026-02-15` `9efef63` - AI routing refactor + Jira outbound sync + Scrum docs.
10. `2026-02-15` `9e25e11` - README alignment with current architecture.
11. `2026-02-15` `742716b` - Jira auto-sync improvements + PlantUML DB schema.
12. `2026-02-15` `f0841e7` - Jira reverse resync, classification updates, and AI metrics fixes.
13. `2026-02-20` `c5ca314` - Jira KB modularization, SLA flows, migrations, and frontend updates.
14. `2026-02-20` `63b832d` - Resume documentation refreshed to match delivered state.

Current pushed head:

- `63b832d2202f0bf02880f555943becc4b35ca02b` on `main`.

---

## 5. Backend implementation summary

Backend stack:

- FastAPI, SQLAlchemy 2.x, Alembic, psycopg, pydantic-settings, python-jose, passlib, httpx.

### 5.1 Router layer

Routers present in `backend/app/routers`:

1. `auth.py`
2. `users.py`
3. `tickets.py`
4. `ai.py`
5. `recommendations.py`
6. `emails.py`
7. `assignees.py`
8. `problems.py`
9. `integrations_jira.py`
10. `sla.py`

Mounted in `backend/app/main.py` under:

- `/api/auth/*`
- `/api/users/*`
- `/api/tickets/*`
- `/api/ai/*`
- `/api/recommendations/*`
- `/api/emails/*`
- `/api/assignees`
- `/api/problems*`
- `/api/integrations/jira/*`
- `/api/sla/*`

### 5.2 Auth and identity

Implemented features:

1. Register, login, logout, refresh.
2. Cookie-based JWT sessions and token-based flows.
3. Email verification by token and by 6-digit code.
4. Password reset flow with one-time tokens.
5. Google OAuth start/callback flow.
6. Auto-signup behavior on email login for unknown accounts.
7. RBAC role support (`admin`, `agent`, `user`, `viewer`).

Primary auth-related tables:

- `users`
- `verification_tokens`
- `password_reset_tokens`
- `refresh_tokens`
- `email_logs`

### 5.3 Ticket management domain

Core capabilities:

1. Ticket CRUD APIs and listing.
2. Stats and insights endpoints.
3. Triage update endpoint for assignee/priority/category updates.
4. Performance and analytics endpoints.
5. Assignment/routing support with capacity and availability checks.
6. Automatic assignment/priority metadata tracking.
7. Comment tracking via `ticket_comments`.

### 5.4 AI service layer

AI module layout in `backend/app/services/ai`:

1. `orchestrator.py`
2. `intents.py`
3. `analytics_queries.py`
4. `formatters.py`
5. `classifier.py`
6. `llm.py`
7. `prompts.py`
8. `quickfix.py`

Implemented behavior:

1. AI classification endpoint for priority/category/recommendations.
2. AI chat endpoint supporting actionable responses and ticket draft outputs.
3. Rule-based fallback when model inference is unavailable.
4. Prompt hardening and confidence/sources guidance.
5. Jira knowledge enrichment via modular `services/jira_kb/*` package.

### 5.5 Problem management domain

Problem management introduced and expanded with:

1. `problems` table/entity.
2. APIs for problem listing, details, AI suggestions.
3. Link/unlink workflows between tickets and problems.
4. Detection/promote patterns for recurring incidents.
5. Problem status lifecycle and recurrence counters.

### 5.6 Recommendations module

Features:

1. DB-backed recommendations entity.
2. Endpoint for listing recommendations.
3. Seed-ready defaults for demo use.

### 5.7 Jira/JSM integration (core)

Integration modules in `backend/app/integrations/jira`:

1. `client.py`
2. `mapper.py`
3. `schemas.py`
4. `service.py`
5. `outbound.py`
6. `auto_reconcile.py`

Inbound capabilities (Jira -> local DB):

1. Webhook endpoint:
   - `/api/integrations/jira/webhook`
   - legacy alias `/api/integrations/jira/upsert`
2. Shared-secret or HMAC signature validation:
   - `X-Jira-Webhook-Secret`
   - `X-Signature` (`sha256=...` supported)
3. Issue + comment upsert with idempotency controls.
4. Reconcile endpoint:
   - `/api/integrations/jira/reconcile`
5. Auto-detection fallback for `project_key` when env value is empty.
6. Background auto-reconcile loop started in app lifespan.

Outbound capabilities (local -> Jira):

1. Best-effort push of newly created local tickets to Jira.
2. Issue payload generation with project/type/priority mapping.
3. Retry fallback to minimal payload on schema mismatch.

n8n role in this architecture:

- Orchestrator only (webhooks, cron, cross-system notifications), not source of truth.

### 5.8 SLA sync and escalation domain

SLA management capabilities:

1. Ticket-level SLA snapshot endpoint for operational visibility.
2. On-demand SLA sync by ticket against Jira SLA data.
3. Batch SLA sync endpoint with status filters and staleness controls.
4. Auto-escalation logic that can raise ticket priority when SLA risk/breach conditions are detected.
5. System actor tagging (`system:n8n`) for auditability of automated escalation actions.

---

## 6. Frontend implementation summary

Frontend stack:

- Next.js App Router, React 19, Tailwind CSS, Radix UI/shadcn-style components, react-hook-form, zod.

### 6.1 Route map

Routes in `frontend/app`:

1. `/` dashboard
2. `/403`
3. `/admin`
4. `/auth/login`
5. `/auth/signup`
6. `/auth/signup-success`
7. `/auth/verify`
8. `/auth/forgot-password`
9. `/auth/reset-password`
10. `/chat`
11. `/tickets`
12. `/tickets/new`
13. `/tickets/[id]`
14. `/recommendations`
15. `/problems`
16. `/problems/[id]`

### 6.2 Major UI components

Core components include:

1. `ticket-form.tsx`
2. `ticket-table.tsx`
3. `ticket-detail.tsx`
4. `ticket-chatbot.tsx`
5. `kpi-cards.tsx`
6. `dashboard-charts.tsx`
7. `performance-metrics.tsx`
8. `operational-insights.tsx`
9. `problem-insights.tsx`
10. `recommendations.tsx`
11. `app-shell.tsx` / `app-sidebar.tsx`
12. `auth-guard.tsx`

### 6.3 Frontend service/libs

In `frontend/lib`:

1. `api.ts` (API transport base)
2. `auth.tsx` (auth context and session handling)
3. `tickets-api.ts`
4. `problems-api.ts`
5. `recommendations-api.ts`
6. `ticket-data.ts`
7. `i18n.tsx` (FR/EN translation layer)
8. `utils.ts`

### 6.4 Frontend behavior highlights

1. Cookie-based auth integration with backend.
2. Role-based route guarding.
3. Dashboard metrics and ticket analytics UI.
4. AI chat/ticket-draft UX flow.
5. Ticket creation and triage interfaces.
6. Problem and recommendation views.

---

## 7. Database and schema evolution

Database: PostgreSQL

Migration history (`backend/alembic/versions`):

1. `0001_initial.py` - initial schema.
2. `0002_recommendations.py` - recommendations table.
3. `0003_add_network_category.py` - ticket category update.
4. `0004_user_auto_assign_fields.py` - user assignment metadata fields.
5. `0005_update_ticket_categories.py` - category evolution.
6. `0006_add_refresh_tokens.py` - refresh token table.
7. `0007_add_intern_seniority.py` - seniority enum update.
8. `0008_add_problem_ticket_category.py` - ticket category includes problem.
9. `0009_add_ticket_performance_metrics.py` - performance metrics fields.
10. `0010_add_password_reset_tokens.py` - password reset token table.
11. `0011_add_verification_code.py` - verification code in tokens.
12. `0012_add_jira_reverse_sync_models.py` - external sync fields + sync state.
13. `0013_rbac_user_role.py` - role-based access additions.
14. `0014_problem_mgmt.py` - problem management entities/relations.
15. `0015_jira_native_sync_fields.py` - Jira-native keys/fields + constraints.
16. `0016_add_kb_chunks_pgvector.py` - KB chunk persistence foundation for semantic retrieval.
17. `0017_add_ticket_sla_fields.py` - ticket-level SLA tracking fields.
18. `0018_add_unique_jira_comment_identity.py` - uniqueness constraints for Jira comment identity.
19. `0019_kb_chunk_identity_uniques.py` - KB chunk uniqueness guarantees.
20. `0020_add_jira_native_waiting_statuses.py` - Jira-native waiting status support.

### 7.1 Current core tables

1. `users`
2. `verification_tokens`
3. `password_reset_tokens`
4. `refresh_tokens`
5. `email_logs`
6. `tickets`
7. `ticket_comments`
8. `problems`
9. `recommendations`
10. `jira_sync_state`
11. `kb_chunks`
12. `alembic_version`

### 7.2 Current key relationships

1. `verification_tokens.user_id -> users.id`
2. `password_reset_tokens.user_id -> users.id`
3. `refresh_tokens.user_id -> users.id`
4. `tickets.problem_id -> problems.id`
5. `ticket_comments.ticket_id -> tickets.id`

### 7.3 Current schema documentation asset

Generated PlantUML schema:

- `docs/db-schema-current.puml`

This includes keys, major constraints, relations, and enum notes.

---

## 8. API inventory (current snapshot)

### 8.1 Auth

`/api/auth`:

1. `POST /register`
2. `POST /login`
3. `POST /email-login`
4. `GET /google/start`
5. `GET /google/callback`
6. `POST /token`
7. `POST /refresh`
8. `POST /token/refresh`
9. `POST /logout`
10. `GET /me`
11. `POST /verify`
12. `POST /verify-code`
13. `POST /resend`
14. `POST /forgot-password`
15. `POST /reset-password`

### 8.2 Users/Admin

`/api/users`:

1. `GET /`
2. `PATCH /{user_id}/role`
3. `PATCH /{user_id}/seniority`
4. `PATCH /{user_id}/specializations`
5. `DELETE /{user_id}`

### 8.3 Tickets

`/api/tickets`:

1. `GET /`
2. `GET /stats`
3. `GET /insights`
4. `GET /performance`
5. `POST /`
6. `GET /{ticket_id}`
7. `PATCH /{ticket_id}`
8. `PATCH /{ticket_id}/triage`

### 8.4 AI

`/api/ai`:

1. `POST /classify`
2. `POST /chat`

### 8.5 Recommendations

`/api/recommendations`:

1. `GET /`

### 8.6 Problems

`/api`:

1. `GET /problems`
2. `GET /problems/{problem_id}`
3. `GET /problems/{problem_id}/ai-suggestions`
4. `POST /problems/detect`
5. `PATCH /problems/{problem_id}`
6. `POST /problems/...` (multiple management actions: link/unlink, etc.)

### 8.7 Jira integrations

`/api/integrations/jira`:

1. `POST /webhook`
2. `POST /upsert` (legacy alias)
3. `POST /reconcile`

### 8.8 SLA

`/api/sla`:

1. `GET /ticket/{ticket_id}`
2. `POST /ticket/{ticket_id}/sync`
3. `POST /run`

### 8.9 Other

1. `GET /api/emails`
2. `GET /api/users/assignees`

---

## 9. Operational and environment configuration

### 9.1 Backend env highlights

Includes:

1. DB/JWT/auth/cookie settings.
2. SMTP and email behavior.
3. OAuth settings.
4. Ollama settings.
5. Jira integration settings:
   - `JIRA_BASE_URL`
   - `JIRA_EMAIL`
   - `JIRA_API_TOKEN`
   - `JIRA_PROJECT_KEY`
   - `JIRA_WEBHOOK_SECRET`
6. Jira auto-reconcile settings:
   - `JIRA_AUTO_RECONCILE_ENABLED`
   - `JIRA_AUTO_RECONCILE_INTERVAL_SECONDS`
   - `JIRA_AUTO_RECONCILE_LOOKBACK_DAYS`
   - `JIRA_AUTO_RECONCILE_STARTUP_DELAY_SECONDS`

### 9.2 Frontend env

- `NEXT_PUBLIC_API_URL`

---

## 10. Project documentation and Scrum artifacts

Available Scrum docs:

1. `docs/scrum/user-stories.md`
2. `docs/scrum/product-backlog.md`
3. `docs/scrum/sprint-backlog.md`
4. `docs/scrum/definition-of-done.md`

Examples of defined stories:

1. AI ticket draft generation from chat.
2. Comment-aware historical recommendations.
3. Natural language analytics query support.

---

## 11. Latest-step details (most recent delivery)

Latest pushed commit:

- `63b832d2202f0bf02880f555943becc4b35ca02b`
- Message: `docs: refresh work resume with latest delivered state`

Latest feature delivery commit:

- `c5ca3141e0af2fd18e0399bd2e2d79ed730a0a75`
- Message: `feat: add Jira KB, SLA flows, and UI updates`

Main latest-step additions:

1. Added migrations `0016` to `0020` for KB chunks, SLA fields, Jira comment identity uniqueness, and waiting-status support.
2. Introduced dedicated SLA endpoints/services (`backend/app/routers/sla.py`, `backend/app/services/sla/`).
3. Split Jira KB logic into a modular package (`backend/app/services/jira_kb/`) with scoring/filtering/formatting helpers.
4. Added embedding service plumbing (`backend/app/services/embeddings.py`) and KB chunk model support.
5. Expanded Jira integration services, including SLA sync support and mapper/client updates.
6. Extended AI routing/classification test coverage (`test_ai_classifier_consensus.py`, `test_ai_routing_plan.py`).
7. Updated frontend dashboard, ticket, problem, and chat pages/components with UX and interaction improvements.
8. Added resume/update documentation for current working state in `docs/WORK_RESUME_README.md`.

---

## 12. Push and file status

Already pushed:

- All code changes up to commit `63b832d...` are pushed to `origin/main`.

---

## 13. Delivered work summary (2026-02-16 to 2026-02-20)

Scope of this delivery phase:

1. UI/UX facelift and interaction polish.
2. Backend Jira KB and SLA capability expansion.
3. Additional migration/test coverage for new backend flows.

### 13.1 Global layout and design-system consistency

1. Shell/header/sidebar visual refresh and tighter focus states:
   - `frontend/components/app-shell.tsx`
   - `frontend/components/app-sidebar.tsx`
2. Shared page primitives normalized for spacing/hierarchy:
   - `frontend/app/globals.css`
   - `page-shell`, `page-hero`, `surface-card`, `section-block`, `section-title`, `section-subtitle`

### 13.2 Dashboard polish (`/`)

1. Structured sections with clearer titles/subtitles and dividers.
2. Added simple skeleton visual states for dashboard blocks.
3. KPI and chart cards now provide better hover/click affordance.
4. Dashboard cards now support hover details and direct navigation to related ticket views.
5. AI before/after metrics section is explicitly labeled to show filters affect only that section.
6. Slight dashboard vertical spacing reduction so lower insights are visible earlier on first load.
7. Files:
   - `frontend/app/page.tsx`
   - `frontend/components/kpi-cards.tsx`
   - `frontend/components/dashboard-charts.tsx`
   - `frontend/components/performance-metrics.tsx`
   - `frontend/components/problem-insights.tsx`
   - `frontend/components/recent-activity.tsx`

### 13.3 Tickets list polish (`/tickets`)

1. Table upgraded with sticky header, zebra striping, improved cell spacing, and hover highlight.
2. Long values are truncated with tooltips (title/assignee/reporter).
3. Filters visually grouped and styled; active filter chips rendered from existing state.
4. Pagination and rows-per-page controls styled consistently.
5. Added reporter search support and related i18n keys for better UX wording.
6. Files:
   - `frontend/components/ticket-table.tsx`
   - `frontend/app/tickets/page.tsx`
   - `frontend/lib/i18n.tsx`

### 13.4 Ticket detail polish (`/tickets/[id]`)

1. Page organized into a clearer 2-column layout:
   - left: main ticket content + comments
   - right: actions/status/metadata + AI recommendations
2. Comments restyled for readability (author identity, timestamp, message bubble).
3. Status/priority/category badge presentation normalized.
4. Loading and not-found states refined visually.
5. Files:
   - `frontend/components/ticket-detail.tsx`
   - `frontend/app/tickets/[id]/page.tsx`

### 13.5 Problems pages polish (`/problems`, `/problems/[id]`)

1. Problems list converted to a card/table hybrid with clearer counters and status surfaces.
2. Detail page sections for root cause/workaround/fix and linked tickets are visually grouped.
3. Empty states improved for list/detail linked-ticket sections.
4. Files:
   - `frontend/app/problems/page.tsx`
   - `frontend/app/problems/[id]/page.tsx`

### 13.6 Chat polish and interaction updates (`/chat`)

1. Chat bubble UX modernized (user vs assistant styles, timestamp micro-label, typing indicator visuals).
2. Ticket draft card now appears only for create-ticket actions (removed for show-ticket digest replies).
3. Critical tickets digest update:
   - Hover on `... et N autres` reveals additional critical-ticket details.
   - Clicking the critical digest response redirects to `/tickets?view=critical`.
4. Files:
   - `frontend/components/ticket-chatbot.tsx`
   - `frontend/app/chat/page.tsx`

### 13.7 Build fix and verification

1. Fixed JSX parse/build error in `frontend/components/performance-metrics.tsx` (tag closure mismatch).
2. Verified production build on `2026-02-17` with:
   - `cd frontend`
   - `npm run build`
3. Build result: success (Next.js `16.1.6`, all routes generated).

### 13.8 Local runtime/model note

1. Local Ollama runtime was switched to `qwen3:4b` via `backend/.env` (`OLLAMA_MODEL=qwen3:4b`).
2. This is local environment configuration, not a committed code-level API/logic change.

### 13.9 Embeddings and pgvector status

1. Current project state does not persist semantic embeddings in Postgres.
2. If embeddings are introduced, `pgvector` can be added incrementally (new extension + columns/tables/indexes) without replacing the whole existing schema.

---

## 14. Known practical notes

1. Jira Cloud cannot call `localhost`; webhook needs a public backend URL.
2. For predictable inbound sync scope, set `JIRA_PROJECT_KEY` explicitly.
3. Keep auto-reconcile enabled as safety net even when webhooks are configured.
4. Apply migrations before runtime testing:
   - `python -m alembic -c alembic.ini upgrade head`

---

## 15. Quick start recap

Backend:

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

Frontend:

```powershell
cd frontend
copy .env.local.example .env.local
npm install
npm run dev
```

---

## 16. Resume intent

This file is intentionally written as a complete, copy-ready project resume from the beginning of the project to the latest completed step, covering frontend, backend, database, integrations, and operational context.

---

## 17. Next implementation phase (requested)

Requested next scope before execution:

1. Implement optional n8n alerts workflow first (before other automation work).
2. Focus on critical-incident and escalation-driven alerting.
3. Trigger problem-launch notifications by email and Microsoft Teams.
4. Make frontend top-bar notification bell actionable (currently static UI badge).

Planned workflow count for this phase:

1. Alerting workflow (n8n): SLA breach risk + critical incidents -> email + Teams.
2. Optional follow-up workflow: problem launch notifier pipeline, if split is preferred for maintainability.

---

## 18. Security hardening update (current session)

Security controls added:

1. Runtime production guardrails in backend settings:
   - Reject weak/default `JWT_SECRET` in production.
   - Reject wildcard CORS (`*`) in production.
   - Warn in non-production when JWT secret is weak.
2. API-level security headers middleware for `/api/*` responses:
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: DENY`
   - `Referrer-Policy: strict-origin-when-cross-origin`
   - `Permissions-Policy`, `Cross-Origin-*`, and restrictive `Content-Security-Policy`
   - `Strict-Transport-Security` enabled in production mode.
3. Secret leak prevention in CI:
   - Added GitHub Action workflow using `gitleaks` on push and pull requests (`.github/workflows/secret-scan.yml`).
4. Repository hygiene checks:
   - Verified no `.env`/`.env.local` files are tracked (only example env files are versioned).
   - Performed targeted static scan for hardcoded credential-like string assignments in source files.

---

## 19. n8n workflows completed in this phase

Completed workflow artifacts:

1. `docs/n8n/workflow_problem_launch_notifier.json`
   - Trigger: `POST /webhook/problem-detected`
   - Purpose: fetch problem details, build email payload, send problem launch alert email, and log automation result.
2. `docs/n8n/workflow_critical_ticket_detector.json`
   - Trigger: `POST /webhook/critical-ticket-detected`
   - Purpose: fetch critical ticket details, build escalation payload, send critical-ticket alert email, and log automation result.

Execution notes:

1. Runtime base URL for n8n backend calls should use container-safe host routing (for Docker: `http://host.docker.internal:8000`).
2. SMTP/Gmail credentials are configured in n8n credentials and are not stored in workflow JSON.
3. `.env` secrets remain local-only and are excluded from Git commits.
4. Both workflows now propagate `trace_id` and `run_id` end-to-end (webhook -> backend fetch headers -> email body -> success/error log nodes) for execution correlation.

---

## 20. AI SLA Risk Scoring (Shadow Mode)

Current implementation adds an AI advisory layer for SLA risk scoring without changing deterministic SLA enforcement.

Key points:

1. Deterministic SLA engine remains the primary decision-maker for escalations.
2. AI evaluates per-ticket breach/escalation risk probabilistically during `POST /api/sla/run`.
3. AI output is persisted for governance/audit in `ai_sla_risk_evaluations`.
4. AI metadata is logged (`model_version`, decision source, reasoning summary).
5. Initial operating mode is `shadow` and does not autonomously escalate.
6. Hybrid safety architecture is preserved: rules decide, AI advises.
7. Future roadmap supports gradual AI-assisted escalation with deterministic confirmation.

Runtime controls:

1. `AI_SLA_RISK_ENABLED=true|false`
2. `AI_SLA_RISK_MODE=shadow|assist` (default `shadow`)

Architecture sketch:

```text
Deterministic Rules -> Escalation Decision
AI Risk Scoring -> Advisory Layer -> Logging
```

Safety note:

- No autonomous AI escalation override is enabled.

---

## 21. SLA Hardening Improvements

1. Dry-run mode for SLA batch runs:
   - `POST /api/sla/run` now accepts `dry_run`.
   - With `dry_run=true`, the batch computes eligibility and proposed SLA actions without side effects.
   - No ticket updates, no auto-escalation writes, no stale-notification creation, and no AI risk persistence are performed.
2. AI SLA risk visibility:
   - Added latest risk endpoint: `GET /api/sla/ticket/{ticket_id}/ai-risk/latest`.
   - Ticket detail UI now includes an `AI SLA Risk (Advisory)` panel that displays score band, confidence, suggested priority, reasoning, and timestamp.
3. Automation audit trail:
   - Added `automation_events` table to log automated actions.
   - SLA flows now record events for:
     - `SLA_SYNC`
     - `AUTO_ESCALATION`
     - `STALE_NOTIFY`
     - `AI_RISK_EVALUATION`
   - Event records include actor, before/after snapshots, metadata, and timestamp for governance and traceability.

## 22. SLA Status Values

Current local SLA status values used by API and sync flows:

1. `ok`: SLA on track (> 30 minutes remaining).
2. `at_risk`: SLA at risk (0 to 30 minutes remaining, not breached).
3. `breached`: SLA already breached.
4. `paused`: SLA timer paused.
5. `completed`: SLA target met.
6. `unknown`: SLA status unavailable or not synced.

---

## 23. KPI framework and objective status (PFE reporting)

### 23.1 Objective status (current)

1. `Ameliorer la performance operationnelle du help desk`: **Partiellement atteint**
   - Functional enablers are implemented (automation, routing, analytics).
   - Full validation requires stable pilot measurements in production-like usage.
2. `Reduire le MTTR`: **Partiellement atteint**
   - MTTR instrumentation is available (`before/after`, global, p90, by priority/category).
   - Final claim depends on baseline-vs-after trend over a fixed time window.
3. `Renforcer la qualite de service`: **Partiellement atteint**
   - Service-quality indicators are now instrumented (including SLA breach KPIs).
   - Business proof still requires periodic KPI review in operations.

### 23.2 KPI set used for validation

Operational performance:

1. Throughput = resolved tickets per week.
2. Backlog = active tickets older than threshold (`7` days by default).
3. FRT = average and median time to first action.
4. `% auto-triaged/auto-assigned without correction`.

MTTR:

1. MTTR global.
2. MTTR by priority (`critical/high/medium/low`).
3. MTTR by category (`infrastructure/network/security/application/service_request/hardware/email/problem`).
4. P90 MTTR.

Service quality:

1. SLA breach rate = breached tickets / tickets with SLA due.
2. First-response SLA breach rate.
3. Resolution SLA breach rate.
4. Placeholders for `reopen_rate`, `first_contact_resolution_rate`, `csat_score` (not yet reliably persisted in current model).

### 23.3 Baseline vs after-deployment template

Use this structure in the final PFE report (weekly or monthly cut):

| KPI | Baseline (Before) | After Deployment | Delta | Target | Status |
| --- | --- | --- | --- | --- | --- |
| Throughput (resolved/week) |  |  |  |  |  |
| Backlog (> 7 days) |  |  |  |  |  |
| FRT avg (hours) |  |  |  |  |  |
| FRT median (hours) |  |  |  |  |  |
| MTTR global (hours) |  |  |  |  |  |
| MTTR P90 (hours) |  |  |  |  |  |
| SLA breach rate (%) |  |  |  |  |  |
| First-response SLA breach rate (%) |  |  |  |  |  |
| Resolution SLA breach rate (%) |  |  |  |  |  |
| Auto-triage no-correction rate (%) |  |  |  |  |  |

Interpretation rule:

1. Keep objective status as `partiellement atteint` until at least one stable pilot window confirms sustained KPI improvement.

---

## 24. Notification delivery enhancement (2026-03-03)

Implemented upgrade for n8n -> backend -> bell notifications with email delivery controls and observability:

1. Data model:
   - `notifications` extended with `metadata_json`, `action_type`, `action_payload`.
   - Added `notification_preferences` (email enabled/min severity/digest/quiet hours).
   - Added `notification_delivery_events` for debug tracing and delivery outcomes.
2. Backend API:
   - `GET/PATCH /api/notifications/preferences`
   - `POST /api/notifications/{id}/send-email` (admin)
   - `POST /api/notifications/digest/run` (admin/agent)
   - `GET /api/notifications/debug-recent` (admin)
   - `GET /api/notifications/analytics` (admin/agent)
3. Delivery policy:
   - `critical`: immediate email + in-app.
   - `high`: in-app + pending hourly digest.
   - `info/warning`: in-app only unless forced by admin resend.
   - Quiet hours respected via preferences, with bypass for `source=sla` + `critical` (`[URGENT]` subject).
4. Email templates:
   - Branded HTML alert template with severity bar, portal CTA, and preference footer.
   - Hourly digest HTML template grouped per user.
5. Frontend:
   - Bell dropdown now grouped by severity (`Critical`, `High`, `Medium/Low`).
   - Critical items are pinned until opened; mark-all skips unread critical.
   - Inline action support (`dismiss`, `approve`, `escalate`) based on `action_type`.
   - Notifications page includes preferences controls and action buttons.
   - Added admin debug page: `/admin/notifications-debug` with filters, resend, digest trigger, and analytics snapshot.

---

## 25. Deterministic mock dataset and Jira alignment tooling (2026-03-15)

Current local working-state update added in this session:

1. Added a fast local-only dataset reset script:
   - `backend/scripts/reset_local_mock_dataset.py`
2. Added a Jira project alignment script:
   - `backend/scripts/sync_local_mock_dataset_to_jira.py`
3. Added an external-AI handoff doc:
   - `docs/AI_HANDOFF_CONTEXT.md`

### 25.1 Local mock dataset reset

Purpose:

1. Replace the existing local sample data quickly.
2. Keep the dataset deterministic for demos and debugging.
3. Avoid Jira push/reconcile when only local DB reset is needed.

Behavior of `reset_local_mock_dataset.py`:

1. Deletes existing local tickets, comments, problems, notifications, recommendations, AI SLA evaluations, and automation events.
2. Seeds exactly:
   - `40` tickets (`TW-MOCK-001` .. `TW-MOCK-040`)
   - `2` problems (`PB-MOCK-01`, `PB-MOCK-02`)
3. Ensures every ticket has:
   - title
   - description
   - assignee
   - reporter
   - ticket type
   - status
   - `due_at`
   - SLA fields
   - at least `2` comments
   - resolution text for resolved tickets
4. Links a subset of tickets to the two problem records.
5. Prints a compact verification summary only.

Verified local DB result on `2026-03-15`:

1. `40` tickets
2. `80` comments
3. `2` problems
4. Ticket type breakdown:
   - `20` incidents
   - `20` service requests
5. Status breakdown:
   - `14` open
   - `13` in-progress
   - `13` resolved
6. SLA breakdown:
   - `10` ok
   - `11` at_risk
   - `11` breached
   - `8` completed
7. `40` tickets with `due_at`
8. `13` resolved tickets with non-empty `resolution`

### 25.2 Jira/JSM alignment script

Reason:

1. Local DB was reduced to the new deterministic 40-ticket dataset.
2. Jira/JSM project `TEAMWILL` still contained `81` issues as of `2026-03-15`.
3. A narrow synchronization path was needed without reconcile/KB refresh.

Behavior of `sync_local_mock_dataset_to_jira.py`:

1. Uses the current local DB dataset as the source of truth.
2. Writes a backup of Jira issue summaries to `.ops_backups/`.
3. Clears local Jira linkage fields on tickets/comments before recreation.
4. Deletes existing issues in the configured Jira project.
5. Pushes the current local dataset to Jira/JSM.
6. Pushes ticket comments after issue creation.
7. Verifies final Jira/local linkage counts.
8. Intentionally skips:
   - Jira reconcile
   - Jira KB refresh
   - SLA sync

Operational caution:

1. The Jira sync script is destructive for the configured Jira project because it deletes existing project issues before recreating the local dataset.
2. Use it only when the local DB should become the source of truth for the Jira project.

### 25.3 External AI handoff support

To make external review easier, a dedicated handoff note was added:

1. `docs/AI_HANDOFF_CONTEXT.md`

It includes:

1. Project summary and architecture snapshot.
2. Current mock dataset state.
3. Jira mismatch context.
4. Important files for Jira reasoning.
5. Constraints and safety notes.
6. A copy-paste prompt for ChatGPT/Claude.

---

## 26. Current workspace state snapshot (2026-03-16)

This section reflects the current working tree in this repository, not only the older pushed history.

### 26.1 Local workspace status

1. Current local `HEAD` observed in the workspace: `f249c34`.
2. The working tree contains additional local modifications and new files beyond the historical pushed-state sections above.
3. Treat the current code on disk as the source of truth for handoff, verification, and debugging.

### 26.2 Current AI recommendation architecture

The platform now uses an evidence-first recommendation path for ticket detail and the main recommendations page.

Operational flow:

```text
ticket/problem context
-> unified_retrieve(...)
-> build_resolution_advice(...)
-> classifier used only for metadata
-> frontend renders action/reasoning/evidence/confidence
```

Key behavior:

1. Evidence priority in `backend/app/services/ai/resolution_advisor.py`:
   - resolved tickets
   - similar tickets
   - KB articles
   - comment-based fixes
   - related problems
2. Retrieval is hybrid in `backend/app/services/ai/retrieval.py`:
   - semantic + lexical
   - query-aware scoring
   - lexical/domain overlap checks
   - mismatch penalties
3. Recommendation output is now action-first and evidence-backed:
   - `recommended_action`
   - `reasoning`
   - `evidence_sources`
   - `probable_root_cause`
   - `confidence`
   - `confidence_band`
   - `match_summary`
   - `next_best_actions`
   - `incident_cluster`
   - `impact_summary`
4. A final action-to-ticket relevance gate prevents weak unrelated fixes from appearing as the main recommendation.

Display modes currently used:

1. `evidence_action`
   - a concrete relevant fix was supported by evidence.
2. `tentative_diagnostic`
   - evidence was weak but aligned enough for a safe deterministic diagnostic step.
3. `no_strong_match`
   - no safe evidence-backed action should be displayed.

Main files:

1. `backend/app/services/ai/retrieval.py`
2. `backend/app/services/ai/resolution_advisor.py`
3. `backend/app/services/ai/orchestrator.py`
4. `backend/app/services/recommendations.py`
5. `backend/app/schemas/ai.py`
6. `backend/app/schemas/recommendation.py`
7. `frontend/components/ticket-detail.tsx`
8. `frontend/components/recommendations.tsx`
9. `frontend/lib/tickets-api.ts`
10. `frontend/lib/recommendations-api.ts`

### 26.2.1 Shared AI resolver workflows

The current platform intentionally uses one shared evidence-first resolver core across three UX layers.

Common backend core:

```text
user/page context
-> retrieval query construction
-> unified_retrieve(...)
-> candidate clustering / family coherence
-> build_resolution_advice(...)
-> typed payload shaping
-> frontend rendering
```

Core rule:

- The same retrieval + advisor logic should stay consistent across chat, `/recommendations`, and `/tickets/[id]`.
- Differences between the three layers should come from input context and response shaping, not from separate recommendation engines.

Workflow 1: chat resolver path

```text
chat message
-> orchestrator intent + entity resolution
-> session/context resolution (`last_ticket_id`, `last_ticket_list`, follow-up references)
-> resolve_ticket_advice(...) when ticket/problem context is available
-> build_* chat payload (`cause_analysis`, `resolution_advice`, `similar_tickets`, etc.)
-> chat UI card/text response
```

Current behavior:

1. Explicit ticket mention is the strongest entity anchor.
2. Follow-ups such as `this ticket`, `why?`, `what should I do next?`, and `which tickets are similar to this one?` reuse the active ticket context.
3. Assistant-generated related suggestion IDs must not silently replace the active ticket.
4. Chat uses the same evidence clusters and advisor output as the page-level recommendation flows, then formats the result into a chat-specific structured payload.

Primary files for chat workflow:

1. `backend/app/services/ai/chat_session.py`
2. `backend/app/services/ai/orchestrator.py`
3. `backend/app/services/ai/chat_payloads.py`
4. `backend/app/services/ai/resolver.py`

Workflow 2: recommendations page path

```text
/recommendations page load
-> frontend recommendations API call
-> backend recommendation service gathers ticket/problem candidates
-> unified_retrieve(...)
-> build_resolution_advice(...)
-> response serialized for recommendations page
-> page renders action/reasoning/evidence/confidence
```

Current behavior:

1. The recommendations page is list-oriented and page-driven rather than conversational.
2. It still relies on the same selected cluster / coherent-family guardrails as chat.
3. The page should therefore surface the same dominant incident family and evidence-backed action that chat would surface for the same ticket.
4. If evidence is weak, the page should degrade to a cautious deterministic diagnostic or no-strong-match state instead of mixing families.

Primary files for recommendations page workflow:

1. `backend/app/services/recommendations.py`
2. `backend/app/services/ai/retrieval.py`
3. `backend/app/services/ai/resolution_advisor.py`
4. `frontend/components/recommendations.tsx`
5. `frontend/lib/recommendations-api.ts`

Workflow 3: ticket detail recommendation path

```text
/tickets/[id] page load
-> frontend ticket detail API call
-> backend fetches ticket context + comments + metadata
-> resolve_ticket_advice(...)
-> unified_retrieve(...)
-> build_resolution_advice(...)
-> ticket detail recommendation card renders evidence-backed advice
```

Current behavior:

1. Ticket detail is the most context-rich non-chat path because it always starts from one resolved ticket.
2. Title, description, recent comments, metadata, and linked problem information are all used to strengthen retrieval precision.
3. The final recommendation card should remain inside one coherent incident family and prefer explicit evidence over generic checklist wording.
4. This page is also the cleanest reference behavior for validating whether chat is staying aligned with the shared resolver core.

Primary files for ticket detail workflow:

1. `backend/app/services/ai/resolver.py`
2. `backend/app/services/ai/retrieval.py`
3. `backend/app/services/ai/resolution_advisor.py`
4. `frontend/components/ticket-detail.tsx`
5. `frontend/lib/tickets-api.ts`

### 26.3 Current SLA advisory architecture

Ticket detail no longer shows an empty SLA AI panel by default.

Current behavior:

1. Every ticket receives an SLA advisory payload.
2. If no persisted AI evaluation is available, the system returns a deterministic advisory.
3. If persisted AI data exists, the panel can show a hybrid advisory.
4. The advisory includes:
   - `risk_score`
   - `band`
   - `confidence`
   - `reasoning`
   - `recommended_actions`
   - `advisory_mode`
   - `sla_elapsed_ratio`
   - `time_consumed_percent`

Primary files:

1. `backend/app/services/ai/ai_sla_risk.py`
2. `backend/app/routers/sla.py`
3. `frontend/components/ticket-detail.tsx`
4. `frontend/lib/tickets-api.ts`

### 26.3.1 AI SLA advisory workflow

The SLA advisory path is separate from the ticket-resolution advisor and should be understood as a parallel advisory layer.

```text
ticket context + SLA fields
-> router/service builds SLA advisory request
-> deterministic SLA baseline is computed first
-> persisted AI SLA evaluation is read if available
-> fallback deterministic advisory is built if no AI evaluation exists
-> ticket detail UI renders SLA advisory panel
```

Operational rule:

1. Deterministic SLA logic remains the control path.
2. AI SLA advisory adds risk interpretation and recommended actions, but does not replace deterministic escalation safeguards.
3. The panel should always return something useful:
   - persisted AI-backed advisory when available
   - deterministic advisory fallback otherwise
4. This keeps SLA guidance stable even when model inference is unavailable or no prior AI evaluation was stored.

What this means architecturally:

1. Ticket-resolution recommendations answer: `what should we do to resolve this incident?`
2. SLA advisory answers: `how risky is the current SLA state and what immediate operational action should be considered?`
3. Both appear on ticket detail, but they are distinct advisory systems with different objectives and safety rules.

### 26.4 Current notifications architecture

Notifications are now backend-driven and preference-aware.

Current behavior:

1. Backend is the source of truth for unread state and delivery routing.
2. Bell unread count reads from backend unread notifications.
3. Mark-one-read and mark-all-read update backend state first, then the frontend refreshes.
4. Critical items can stay visually pinned until opened.
5. Delivery routes are explicit:
   - `in_app_only`
   - `direct_email`
   - `digest_queue`
   - `n8n_workflow`
6. Duplicate suppression and material-change checks are implemented for noisy event classes.

Primary files:

1. `backend/app/services/notifications_service.py`
2. `backend/app/routers/notifications.py`
3. `frontend/components/app-shell.tsx`
4. `frontend/app/notifications/page.tsx`
5. `frontend/app/admin/notifications-debug/page.tsx`
6. `frontend/lib/notifications-api.ts`

### 26.5 Notification demo artifact

To prove the bell and notification flow locally, a deterministic seed script was added:

1. `backend/scripts/seed_notification_demo.py`

Demo entities created by that script:

1. Ticket: `TW-DEMO-NOTIFY-01`
2. Problem: `PB-DEMO-NOTIFY-01`

Use this demo when validating:

1. bell unread count
2. notification page items
3. pinned critical notifications
4. mark-read and mark-all-read behavior
5. delivery audit visibility

### 26.6 Latest verification status

Most recent verified outcomes in the current workspace:

1. `pytest backend/tests -q` passed with `92` tests during the recommendation hardening pass.
2. The backend recommendation and SLA paths compile and run with the deterministic-first architecture described above.
3. Frontend type-checking still has pre-existing unrelated issues in:
   - `frontend/app/page.tsx`
   - `frontend/components/ui/calendar.tsx`

---

## 27. Current validation tickets and known practical cases

Useful tickets for validating current behavior:

1. `TW-MOCK-023`
   - good `/recommendations` page validation target for critical relay/certificate behavior.
2. `TW-MOCK-025`
   - recommendation precision regression target for payroll export/date-format evidence.
   - expected behavior: recommendation stays in export/date-format/application space and does not drift to hardware/mail fixes.
3. `TW-DEMO-NOTIFY-01`
   - notification bell/page/delivery demo ticket created by `seed_notification_demo.py`.

Known remaining precision gap:

1. `TW-MOCK-019` (`CRM sync job stalls after token rotation`) is a known example where recommendation quality can still be poor.
2. Observed bad output:
   - a mail/relay certificate/queue action was selected for a CRM/token/stalled-worker ticket.
3. Strong implication:
   - KB/local evidence filtering is improved but not perfect.
   - Some low-quality KB matches can still survive on generic overlap instead of domain/entity overlap.
4. If this case is being worked next, start in:
   - `backend/app/services/ai/retrieval.py`
   - `backend/app/services/ai/resolution_advisor.py`

---

## 28. Recommended reading order for the next AI or engineer

If the next task is about AI recommendations:

1. `backend/app/services/ai/retrieval.py`
2. `backend/app/services/ai/resolution_advisor.py`
3. `backend/app/services/ai/orchestrator.py`
4. `backend/app/services/recommendations.py`
5. `frontend/lib/tickets-api.ts`
6. `frontend/lib/recommendations-api.ts`
7. `frontend/components/ticket-detail.tsx`
8. `frontend/components/recommendations.tsx`

If the next task is about SLA advisory:

1. `backend/app/services/ai/ai_sla_risk.py`
2. `backend/app/routers/sla.py`
3. `frontend/lib/tickets-api.ts`
4. `frontend/components/ticket-detail.tsx`

If the next task is about notifications:

1. `backend/app/services/notifications_service.py`
2. `backend/app/routers/notifications.py`
3. `backend/scripts/seed_notification_demo.py`
4. `frontend/components/app-shell.tsx`
5. `frontend/app/notifications/page.tsx`
6. `frontend/app/admin/notifications-debug/page.tsx`

If the next task is about Jira/local dataset alignment:

1. `backend/scripts/reset_local_mock_dataset.py`
2. `backend/scripts/sync_local_mock_dataset_to_jira.py`
3. `backend/app/integrations/jira/client.py`
4. `backend/app/integrations/jira/outbound.py`
5. `backend/app/integrations/jira/service.py`
