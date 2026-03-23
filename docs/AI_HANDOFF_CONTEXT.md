# AI Handoff Context

Use this file when you want to ask ChatGPT, Claude, or another AI assistant about this repository.

Important safety note:
- Do not share `backend/.env`, `frontend/.env.local`, root `.env`, API tokens, SMTP passwords, Jira tokens, or files under `.ops_backups/`.
- If you send code externally, send only the files relevant to your question.

## 1. What This Repository Is

Project name:
- `jira-ticket-managementv2`

Purpose:
- Internal ITSM platform for TeamWill with ticket management, AI-assisted triage, evidence-backed recommendations, SLA advisory, notifications, problem management, and Jira Service Management integration.

Main stack:
- Backend: FastAPI, SQLAlchemy, Alembic, PostgreSQL
- Frontend: Next.js App Router, React, Tailwind
- Integrations: Jira Service Management, optional n8n, optional Ollama/local LLM

## 2. Current High-Level Architecture

Main application flow:
- `frontend/` calls backend REST APIs under `/api/*`
- `backend/` is the system of record for local tickets, comments, problems, recommendations, SLA snapshots, and notifications
- PostgreSQL stores local application state
- Jira/JSM is supported for inbound and outbound sync
- n8n is used only where workflow orchestration or cross-system fanout is useful

Important backend areas:
- `backend/app/routers/` HTTP endpoints
- `backend/app/services/` business logic
- `backend/app/services/ai/` recommendation, retrieval, orchestration, SLA advisory
- `backend/app/services/notifications_service.py`
- `backend/app/integrations/jira/` Jira client, mapper, outbound sync, reverse sync
- `backend/app/models/` SQLAlchemy models
- `backend/alembic/versions/` migrations

Important frontend areas:
- `frontend/app/` routes
- `frontend/components/ticket-detail.tsx`
- `frontend/components/recommendations.tsx`
- `frontend/components/app-shell.tsx`
- `frontend/app/notifications/page.tsx`
- `frontend/lib/tickets-api.ts`
- `frontend/lib/recommendations-api.ts`
- `frontend/lib/notifications-api.ts`

## 3. Current AI Recommendation Architecture

The recommendation system is no longer mainly classifier-generated text. It is now evidence-first and deterministic-first for the main recommendation surfaces.

Current flow:

```text
ticket/problem context
-> unified_retrieve(...)
-> build_resolution_advice(...)
-> classifier only for metadata like priority/category/assignee
-> frontend renders action/reasoning/evidence/confidence
```

Primary files:
- `backend/app/services/ai/retrieval.py`
- `backend/app/services/ai/resolution_advisor.py`
- `backend/app/services/ai/orchestrator.py`
- `backend/app/services/recommendations.py`
- `backend/app/schemas/ai.py`
- `backend/app/schemas/recommendation.py`
- `frontend/components/ticket-detail.tsx`
- `frontend/components/recommendations.tsx`
- `frontend/lib/tickets-api.ts`
- `frontend/lib/recommendations-api.ts`

Evidence priority in the resolver:
1. resolved tickets
2. similar tickets
3. KB articles
4. comment-based fixes
5. related problems

Key current output fields:
- `recommended_action`
- `reasoning`
- `evidence_sources`
- `probable_root_cause`
- `confidence`
- `confidence_band`
- `recommendation_mode`
- `source_label`
- `match_summary`
- `next_best_actions`
- `incident_cluster`
- `impact_summary`
- `action_relevance_score`
- `filtered_weak_match`
- `display_mode`

Current display modes:
1. `evidence_action`
   - a relevant fix is supported by evidence
2. `tentative_diagnostic`
   - evidence is weak but aligned enough for a safe diagnostic next step
3. `no_strong_match`
   - no safe evidence-backed solution should be shown yet

Important current guardrails:
- retrieval uses query-aware scoring
- lexical/domain overlap is checked
- low-confidence mismatched actions are filtered before reaching the UI
- if no strong match exists, the system should show a safe deterministic diagnostic step or no-strong-match state

## 4. Current SLA Advisory Architecture

Ticket detail includes a deterministic-first SLA advisory instead of an empty AI panel.

Primary files:
- `backend/app/services/ai/ai_sla_risk.py`
- `backend/app/routers/sla.py`
- `frontend/components/ticket-detail.tsx`
- `frontend/lib/tickets-api.ts`

Current behavior:
- every ticket gets an SLA advisory payload
- if there is no persisted AI evaluation, advisory mode is `deterministic`
- if persisted AI data exists, advisory mode can be `hybrid`
- the panel shows:
  - `risk_score`
  - `band`
  - `confidence`
  - `reasoning`
  - `recommended_actions`
  - `advisory_mode`
  - `sla_elapsed_ratio`
  - `time_consumed_percent`

## 5. Current Notifications Architecture

Notifications are backend-driven, preference-aware, and auditable.

Primary files:
- `backend/app/services/notifications_service.py`
- `backend/app/routers/notifications.py`
- `backend/app/models/notification.py`
- `backend/app/models/notification_preference.py`
- `frontend/components/app-shell.tsx`
- `frontend/app/notifications/page.tsx`
- `frontend/app/admin/notifications-debug/page.tsx`
- `frontend/lib/notifications-api.ts`

Current behavior:
- backend is the source of truth for unread state
- bell unread count comes from backend unread notifications
- read-one and read-all update backend state first
- critical notifications can remain visually pinned until opened
- delivery routes are explicit:
  - `in_app_only`
  - `direct_email`
  - `digest_queue`
  - `n8n_workflow`
- duplicate suppression and material-change detection are implemented for noisy event classes

## 6. Current Mock Dataset and Demo Artifacts

Deterministic local dataset:
- `backend/scripts/reset_local_mock_dataset.py`
- seeds exactly 40 tickets: `TW-MOCK-001` through `TW-MOCK-040`
- seeds exactly 2 problems: `PB-MOCK-01`, `PB-MOCK-02`

Jira alignment script:
- `backend/scripts/sync_local_mock_dataset_to_jira.py`
- destructive for the configured Jira project
- deletes existing project issues and recreates the local dataset
- intentionally skips reconcile, KB refresh, and SLA sync

Notification demo script:
- `backend/scripts/seed_notification_demo.py`
- creates:
  - ticket `TW-DEMO-NOTIFY-01`
  - problem `PB-DEMO-NOTIFY-01`
- use this to verify bell unread count, notification page behavior, pinned critical items, and delivery audit visibility

Useful validation tickets:
1. `TW-MOCK-023`
   - good `/recommendations` validation target for critical relay/certificate behavior
2. `TW-MOCK-025`
   - good recommendation-precision regression target for payroll export/date-format behavior
3. `TW-DEMO-NOTIFY-01`
   - good notifications demo target

## 7. Known Current Gap

Known remaining recommendation precision issue:
- `TW-MOCK-019` (`CRM sync job stalls after token rotation`) can still produce an unrelated mail/relay KB-style recommendation

Why this matters:
- retrieval and relevance gating are much better than before, but some KB/local weak matches can still survive on generic overlap instead of domain/entity overlap

If you are debugging this next, start here:
- `backend/app/services/ai/retrieval.py`
- `backend/app/services/ai/resolution_advisor.py`

## 8. Fast Reading Order for Another AI

If the task is about AI recommendations:
1. `backend/app/services/ai/retrieval.py`
2. `backend/app/services/ai/resolution_advisor.py`
3. `backend/app/services/ai/orchestrator.py`
4. `backend/app/services/recommendations.py`
5. `frontend/lib/tickets-api.ts`
6. `frontend/lib/recommendations-api.ts`
7. `frontend/components/ticket-detail.tsx`
8. `frontend/components/recommendations.tsx`

If the task is about SLA advisory:
1. `backend/app/services/ai/ai_sla_risk.py`
2. `backend/app/routers/sla.py`
3. `frontend/lib/tickets-api.ts`
4. `frontend/components/ticket-detail.tsx`

If the task is about notifications:
1. `backend/app/services/notifications_service.py`
2. `backend/app/routers/notifications.py`
3. `backend/scripts/seed_notification_demo.py`
4. `frontend/components/app-shell.tsx`
5. `frontend/app/notifications/page.tsx`
6. `frontend/app/admin/notifications-debug/page.tsx`

If the task is about Jira/local dataset alignment:
1. `backend/scripts/reset_local_mock_dataset.py`
2. `backend/scripts/sync_local_mock_dataset_to_jira.py`
3. `backend/app/integrations/jira/client.py`
4. `backend/app/integrations/jira/outbound.py`
5. `backend/app/integrations/jira/service.py`

## 9. Important Constraints

Current working constraints:
- Prefer deterministic-first solutions
- Avoid heavy LLM generation on page-load paths
- Avoid long network-heavy Jira operations unless explicitly needed
- Do not run Jira reconcile or KB refresh unless explicitly requested
- Prefer local DB operations when possible
- Do not use destructive git commands
- Do not assume access to secrets or `.env` files when asking another AI

## 10. Copy-Paste Prompt for Another AI

You can paste this into ChatGPT or Claude and then attach only the files relevant to your question:

```text
I am working on a repository called `jira-ticket-managementv2`.

It is an internal ITSM platform for TeamWill built with:
- FastAPI + SQLAlchemy + Alembic + PostgreSQL on the backend
- Next.js App Router + React + Tailwind on the frontend
- Jira Service Management integration, optional n8n workflows, and optional local LLM usage

Current architecture to understand first:
- Ticket detail and the main `/recommendations` page already use an evidence-first recommendation pipeline:
  ticket/problem context
  -> unified_retrieve(...)
  -> build_resolution_advice(...)
  -> classifier only for metadata
  -> UI renders recommended action, reasoning, evidence, confidence, and next best actions
- The resolver prioritizes:
  1. resolved tickets
  2. similar tickets
  3. KB articles
  4. comment-based fixes
  5. related problems
- The recommendation system is deterministic-first and includes relevance gating, mismatch filtering, confidence bands, and UI display modes:
  - evidence_action
  - tentative_diagnostic
  - no_strong_match
- Ticket detail also includes a deterministic/hybrid SLA advisory panel.
- Notifications are backend-driven, preference-aware, and the bell unread count is synced from backend state.

Known current issue:
- `TW-MOCK-019` (`CRM sync job stalls after token rotation`) can still produce an unrelated mail/relay KB-style recommendation.
- If helping with recommendation precision, inspect retrieval and resolver relevance filtering first.

Helpful files:
- `backend/app/services/ai/retrieval.py`
- `backend/app/services/ai/resolution_advisor.py`
- `backend/app/services/ai/orchestrator.py`
- `backend/app/services/recommendations.py`
- `backend/app/services/notifications_service.py`
- `backend/app/services/ai/ai_sla_risk.py`
- `backend/app/routers/sla.py`
- `frontend/components/ticket-detail.tsx`
- `frontend/components/recommendations.tsx`
- `frontend/components/app-shell.tsx`
- `frontend/lib/tickets-api.ts`
- `frontend/lib/recommendations-api.ts`
- `frontend/lib/notifications-api.ts`

Constraints:
- Do not assume access to secrets or `.env` files
- Prefer deterministic/local-first solutions
- Avoid heavy LLM suggestions on page-load paths
- Avoid destructive git commands
- Do not propose Jira reconcile or KB refresh unless truly needed

Please help me with: [replace this with your exact question]
```

## 11. Suggested Attachments

When asking another AI, attach only what is needed:
- For recommendation questions:
  - `backend/app/services/ai/retrieval.py`
  - `backend/app/services/ai/resolution_advisor.py`
  - `backend/app/services/ai/orchestrator.py`
  - `backend/app/services/recommendations.py`
  - the relevant frontend API/component files
- For SLA questions:
  - `backend/app/services/ai/ai_sla_risk.py`
  - `backend/app/routers/sla.py`
  - relevant ticket detail frontend files
- For notifications questions:
  - `backend/app/services/notifications_service.py`
  - `backend/app/routers/notifications.py`
  - `backend/scripts/seed_notification_demo.py`
  - relevant bell/page frontend files
- For Jira questions:
  - `backend/scripts/reset_local_mock_dataset.py`
  - `backend/scripts/sync_local_mock_dataset_to_jira.py`
  - `backend/app/integrations/jira/*`
