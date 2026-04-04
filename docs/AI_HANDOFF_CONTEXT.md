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
- `backend/app/services/ai/summarization.py` — AI ticket summarization (TTL cache + RAG)
- `backend/app/services/ai/orchestrator.py` — chat handler; problems are now first-class Tier 1 shortcuts
- `backend/app/services/notifications_service.py`
- `backend/app/integrations/jira/` Jira client, mapper, outbound sync, reverse sync
- `backend/app/models/` SQLAlchemy models
- `backend/alembic/versions/` migrations (chain ends at 0033_add_ticket_summary)

Important frontend areas:
- `frontend/app/` routes
- `frontend/components/ticket-detail.tsx`
- `frontend/components/recommendations.tsx`
- `frontend/components/app-shell.tsx`
- `frontend/app/notifications/page.tsx`
- `frontend/lib/tickets-api.ts` — includes `fetchTicketSummary()`
- `frontend/lib/recommendations-api.ts`
- `frontend/lib/notifications-api.ts`
- `frontend/lib/badge-utils.ts` — centralized `getBadgeStyle()` for all status/priority badges
- `frontend/components/ui/confidence-bar.tsx` — ConfidenceBar component (4 bands)
- `frontend/components/ui/insight-popup.tsx` — InsightPopup (desktop modal + mobile bottom sheet)

Problem chat — first-class entities (as of 2026-03-26):
- Problems are routed via Tier 1 shortcuts, not the LLM/retrieval pipeline
- ChatIntent now includes `problem_listing`, `problem_detail`, `problem_drill_down`, `recommendation_listing`
- Session state tracks `last_problem_id` and `last_problem_list` for contextual follow-ups
- STATUS_KEYWORD_MAP in conversation_policy.py drives status-filtered problem queries

LLM general-knowledge advisory trust hierarchy (display_mode):
  `evidence_action` > `tentative_diagnostic` > `llm_general_knowledge` > `no_strong_match`
  The `llm_general_knowledge` mode fires when retrieval returns no dominant cluster and LLM succeeds.
  Confidence is always fixed at 0.25 (LLM_GENERAL_ADVISORY_CONFIDENCE). Never show Apply button on this type.

## 3. Current AI Recommendation Architecture

The recommendation system is no longer mainly classifier-generated text. It is now evidence-first and deterministic-first for the main recommendation surfaces.

Current flow:

```text
ticket/problem context
-> unified_retrieve(...)
-> build_resolution_advice(...)
-> classifier metadata derived from the same grounded retrieval families
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
- `llm_general_advisory` (set when `display_mode === "llm_general_knowledge"`)
- `knowledge_source` (set to `"llm_general_knowledge"` when LLM advisory is active)

Current display modes (trust hierarchy — highest to lowest):
1. `evidence_action`
   - a relevant fix is supported by evidence
2. `tentative_diagnostic`
   - evidence is weak but aligned enough for a safe diagnostic next step
3. `service_request`
   - planned fulfillment workflow; render runbook-style guidance instead of incident diagnosis
   - no root-cause section, no incident evidence cluster, no Apply-style remediation framing
4. `llm_general_knowledge`
   - no local evidence; LLM general IT knowledge advisory provided as fallback
   - rendered with blue/info styling; confidence fixed at 0.25; no Apply button
   - fields: `llm_general_advisory.probable_causes`, `suggested_checks`, `escalation_hint`
   - promoted from `no_strong_match` when `build_llm_general_advisory()` succeeds
5. `no_strong_match`
   - no safe evidence-backed solution should be shown yet
   - shown when `llm_general_knowledge` advisory also fails or is disabled

Important current guardrails:
- retrieval uses query-aware scoring
- retrieval now tracks contrasted / false-positive domains and topics via `negative_domains` / `negative_topics`
- lexical/domain overlap is checked
- retrieval confidence is now consensus-aware, not top-hit-only
- mixed-family evidence lowers confidence and can force manual-triage / no-strong-match behavior
- classifier strong matches are filtered through the same grounded issue-matching logic as retrieval
- low-confidence mismatched actions are filtered before reaching the UI
- if no strong match exists, the system should show a safe deterministic diagnostic step or no-strong-match state
- service requests now use a dedicated fulfillment-family registry instead of reusing incident families directly
  - profile facets: `operation`, `resource`, `governance`, `target_terms`
  - family examples: `account_provisioning`, `access_provisioning`, `credential_rotation`, `scheduled_maintenance`, `notification_distribution_change`, `integration_configuration`, `device_provisioning`, `reporting_workspace_setup`
  - the same profile now drives service-request guidance, candidate ranking, and similar-ticket filtering
  - guidance gating is now profile-first for unknown/ambiguous planned workflows: a strong fulfillment profile can activate `service_request` mode even if the coarse classifier only inferred a domain such as `application` or `hardware`
  - for tickets already marked as service requests, the gate now also accepts broader fulfillment shapes such as `operation + governance` or `resource + governance` so low-similarity planned tasks still receive a runbook recommendation instead of falling into `no_strong_match`
  - ticket-detail recommendation requests now fall back to the stored ticket metadata (`ticket_type`) when the classifier returns `None`, so existing service-request tickets are less likely to be misrouted into the incident resolver
  - explicit `incident` classification still wins, so genuine failures like dashboard/export errors remain on the incident resolver path

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

## 7. Current Grounding Notes

Recent core fix:
- classification no longer trusts raw semantic Jira hits by default; strong matches are now passed through grounded issue filtering and cluster-consensus checks first
- retrieval confidence now blends raw hit strength with cluster coherence/support instead of trusting the strongest single row
- comment evidence is now attached only to already-grounded Jira issue families, which reduces false "rich evidence" amplification

Residual risk:
- retrieval quality still depends on the taxonomy/coherence model, so broad cross-cutting language can still degrade precision when the query itself is highly mixed or underspecified
- when evidence splits cleanly across families, the system should now prefer low-confidence/manual-triage behavior rather than forcing an incorrect operational diagnosis

If you are debugging this next, start here:
- `backend/app/services/ai/retrieval.py`
- `backend/app/services/ai/resolution_advisor.py`
- `backend/app/services/ai/classifier.py`

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

Security constraints identified in 2026-03-26 autonomous review:
- NEVER re-introduce `ast.literal_eval` in the LLM output parsing path. Only `json.loads` is permitted. The test `backend/tests/test_llm_json_extraction.py` regresses against this.
- NEVER add `asyncio.run()` inside a synchronous FastAPI endpoint handler. All endpoints that call async LLM functions must themselves be `async def`. The existing `GET /api/tickets/{ticket_id}/summary` handler is a known violation (tracking: priority 1 in AUTONOMOUS_REVIEW_REPORT.md).
- NEVER remove `rate_limit()` from a public-facing endpoint's dependencies without explicit justification. The `POST /api/notifications/system` endpoint currently has no rate limiting (tracking: priority 2 in AUTONOMOUS_REVIEW_REPORT.md).
- ALWAYS strip or sanitize user-supplied `title`, `description`, and chat `question` fields before interpolating them into LLM prompt strings. The `core/sanitize.py` helpers clean control characters but do NOT strip prompt-injection markers. A separate stripping step is needed in `prompts.py` before `ollama_generate()` calls.
- NEVER log `user.email` at INFO level in auth or user-management services. Use `user.id` (UUID) for auditability without PII exposure. Applies to all log lines in `backend/app/services/auth.py` and `backend/app/services/users.py`.
- NEVER make `allow_methods=["*"]` and `allow_headers=["*"]` permanent in production CORS config. These should be restricted to the specific methods and headers used by the frontend before production deployment.
- NEVER add new endpoints to the `ai` or `recommendations` routers without verifying authentication and role guards. Two analytics endpoints (`GET /api/ai/feedback/analytics`, `GET /api/recommendations/feedback-analytics`) currently rely solely on router-level guards with no per-endpoint role check and no explicit `current_user` parameter.

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
  - service_request
  - no_strong_match
- Ticket detail also includes a deterministic/hybrid SLA advisory panel.
- Notifications are backend-driven, preference-aware, and the bell unread count is synced from backend state.

Residual AI quality risks:
- `TW-MOCK-019` (`CRM sync job stalls after token rotation`) is still the best replay case for cross-domain contamination checks, but the current expected behavior is now downgrade/manual-triage or same-family application guidance — not a confident mail/relay answer.
- Service requests are now first-class in ticket detail and recommendations, but the newest remaining quality gap is family specificity: broad or underspecified requests can still fall back to generic runbook guidance if the extracted fulfillment profile is weak.
- Confidence calibration is still policy-tuned; if recommendation quality regresses, inspect retrieval conflict scoring and guidance downgrade thresholds first.

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
