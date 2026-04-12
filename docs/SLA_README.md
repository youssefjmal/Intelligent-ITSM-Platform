# SLA Workflow Documentation

This document explains how SLA works end-to-end in the Teamwill Intern ITSM platform, including sync, status computation, escalation, notifications, AI advisory scoring, and operational examples.

## 1. Scope and goals

SLA in this app is built around Jira Service Management SLA data and local policy logic.

Primary goals:

1. Keep ticket SLA fields synchronized from Jira.
2. Classify SLA state in a local, UI-friendly status model.
3. Auto-escalate ticket priority when risk/breach conditions are met.
4. Notify stakeholders for escalations and stale ticket status.
5. Preserve automation audit history and AI advisory traceability.

## 2. SLA data model on tickets

SLA-related fields are stored on the `tickets` table:

1. `sla_status` (`ok | at_risk | breached | paused | completed | unknown`)
2. `sla_first_response_due_at`
3. `sla_resolution_due_at`
4. `sla_first_response_breached`
5. `sla_resolution_breached`
6. `sla_first_response_completed_at`
7. `sla_resolution_completed_at`
8. `sla_remaining_minutes`
9. `sla_elapsed_minutes`
10. `sla_last_synced_at`
11. `jira_sla_payload` (raw Jira SLA payload snapshot)

Priority escalation trace fields:

1. `priority_auto_escalated`
2. `priority_escalation_reason`
3. `priority_escalated_at`

Code reference:

1. `backend/app/models/ticket.py`

## 3. SLA statuses used in the app

The app uses these local SLA statuses:

1. `ok`
2. `at_risk`
3. `breached`
4. `paused`
5. `completed`
6. `unknown`

Computation highlights:

1. If first-response or resolution SLA is breached -> `breached`
2. If Jira status is paused/completed -> `paused` or `completed`
3. If remaining time is 0..30 minutes -> `at_risk`
4. Otherwise fallback to `ok`/`unknown` based on normalized Jira state

Code reference:

1. `backend/app/integrations/jira/sla_sync.py` (`_compute_sla_status`, `parse_jira_sla`)

## 4. End-to-end workflow

### 4.1 Trigger paths that can run SLA sync/escalation

SLA sync can happen through several paths:

1. Jira inbound sync (webhook/reconcile):
   - `POST /api/integrations/jira/webhook`
   - `POST /api/integrations/jira/reconcile`
2. Local ticket -> Jira link creation:
   - `ensure_jira_link_for_ticket` performs SLA sync after link creation.
3. Manual per-ticket endpoint:
   - `POST /api/sla/ticket/{ticket_id}/sync`
4. Batch endpoint (typically scheduler-driven):
   - `POST /api/sla/run`
   - current n8n workflow calls this every 15 minutes (`docs/n8n/workflow_sla_breach_alerting.json`).

### 4.2 Sequence (operational view)

```text
Trigger (Jira webhook / reconcile / manual sync / n8n batch)
  -> Fetch Jira SLA payload (/rest/servicedeskapi/request/{issue_key}/sla)
  -> Normalize SLA fields and persist on ticket
  -> Recompute local sla_status (including at_risk window)
  -> Evaluate deterministic auto-escalation policy
  -> Create SLA notifications when needed
  -> Persist automation events (audit trail)
  -> Optionally evaluate + persist AI SLA risk advisory
  -> Frontend surfaces status/risk in ticket table, detail panel, and notifications center
```

## 5. Jira SLA parsing and normalization

Jira client path:

1. `/rest/servicedeskapi/request/{issue_key}/sla`

Normalization strategy:

1. Extract SLA entries from variants like `slas`, `values`, `slaValues`, nested `sla.values`.
2. Identify first-response metric by name hints:
   - `first response`, `first-response`, `firstresponse`, `response`
3. Identify resolution metric by hints:
   - `time to resolution`, `resolution`, `resolve`, `resolved`
4. Parse:
   - due/target timestamps
   - breached/completed/paused
   - remaining and elapsed time (millis -> minutes)
5. Persist normalized values + raw payload.

Failure behavior:

1. Jira SLA endpoint 401/403/404 returns empty payload (no crash).
2. Sync helper is best-effort and returns `False` if fetch fails.

Code references:

1. `backend/app/integrations/jira/client.py`
2. `backend/app/integrations/jira/sla_sync.py`

## 6. Deterministic auto-escalation policy

Escalation rules are deterministic and priority-only:

1. Resolution SLA breached -> escalate to `critical`
2. First response SLA breached:
   - if current priority is below `high`, escalate to `high`
3. Remaining SLA <= 10 minutes:
   - if current priority is below `high`, escalate to `high`
4. Remaining SLA <= 30 minutes:
   - escalate one step (`low->medium`, `medium->high`, `high->critical`)
5. No escalation for `resolved`/`closed` tickets
6. Cooldown: no new escalation if last escalation < 6 hours ago

Escalation metadata:

1. `priority_auto_escalated=true`
2. `priority_escalation_reason` (ex: `jira_sla_resolution_breached`)
3. `priority_escalated_at`

Code reference:

1. `backend/app/services/sla/auto_escalation.py`

## 7. Notification flow for SLA

### 7.1 Escalation notifications

When a ticket is escalated:

1. Source: `sla`
2. Severity: `high`
3. Title pattern: `SLA auto-escalation: {ticket_id}`
4. Link: `/tickets/{ticket_id}`
5. Duplicate cooldown: 30 minutes
6. Recipients: `resolve_ticket_recipients(..., include_admins=True)`:
   - admins
   - reporter (by `reporter_id`)
   - assignee (by assignee identity match)
   - reporter name match

### 7.2 Stale-status notifications

When ticket status does not change for too long:

1. Condition:
   - ticket not `resolved`/`closed`
   - `updated_at <= now - stale_status_minutes`
2. Source: `sla`
3. Severity: `warning`
4. Link: `/tickets/{ticket_id}`
5. Default stale threshold: 120 minutes (configurable per `/api/sla/run` payload)
6. Duplicate suppression:
   - per user + link + unread + source `sla`
   - cooldown 120 minutes
7. Recipients:
   - all admins
   - assignee user if resolvable

Code references:

1. `backend/app/routers/sla.py`
2. `backend/app/services/notifications_service.py`

### 7.3 Email delivery behavior for SLA notifications

Email dispatch depends on user notification preferences:

1. `critical` notifications are immediate (SLA source can bypass quiet hours).
2. `high` notifications are marked for hourly digest (`pending-digest`).
3. `warning/info` are in-app unless forced/manual send.

This means SLA escalation (`high`) typically appears in-app first and is included in digest flow unless an admin triggers direct send.

Code reference:

1. `backend/app/services/notifications_service.py`

## 8. Automation audit trail

All SLA automation writes traceable events in `automation_events`:

1. `SLA_SYNC`
2. `AUTO_ESCALATION`
3. `STALE_NOTIFY`
4. `AI_RISK_EVALUATION`

Stored metadata can include before/after snapshots and context such as reason, notified count, model info.

Code references:

1. `backend/app/models/automation_event.py`
2. `backend/app/routers/sla.py`

## 9. AI SLA risk advisory (shadow/assist)

AI risk scoring is advisory and does not replace deterministic rules.

Controls:

1. `AI_SLA_RISK_ENABLED=true|false`
2. `AI_SLA_RISK_MODE=shadow|assist` (default: `shadow`)

Runtime behavior in `/api/sla/run`:

1. Runs only when AI is enabled and `dry_run=false`.
2. Evaluates risk per processed ticket.
3. Persists records in `ai_sla_risk_evaluations`.
4. Adds `AI_RISK_EVALUATION` audit event.
5. Returns batch summary:
   - `evaluated`
   - `avg_risk_score`
   - `high_risk_detected` (`risk_score >= 80`)
   - `shadow_mode`

Frontend:

1. Ticket detail calls `GET /api/sla/ticket/{ticket_id}/ai-risk/latest`.
2. Panel label: `AI SLA Risk (Advisory)`.

Code references:

1. `backend/app/services/ai/ai_sla_risk.py`
2. `backend/app/routers/sla.py`
3. `frontend/components/ticket-detail.tsx`
4. `frontend/lib/tickets-api.ts`

## 10. SLA API reference

Base prefix: `/api/sla`

### 10.1 `GET /ticket/{ticket_id}`

Returns current persisted SLA snapshot for one ticket.

### 10.2 `POST /ticket/{ticket_id}/sync`

Runs immediate SLA sync for one ticket, applies deterministic escalation, and may create escalation notifications.

Allowed roles:

1. `admin`
2. `agent`

### 10.3 `GET /metrics`

Computes SLA metrics over Jira-linked tickets.

Query:

1. `status` optional ticket-status filter

Response fields:

1. `total_tickets`
2. `sla_breakdown`
3. `breach_rate`
4. `at_risk_rate`
5. `avg_remaining_minutes`

### 10.4 `GET /ticket/{ticket_id}/ai-risk/latest`

Returns latest AI advisory row for a ticket, or `{ "ticket_id": "...", "latest": null }` if absent.

### 10.5 `POST /run`

Batch SLA sync/evaluation endpoint.

Payload (`SLABatchRunRequest`):

1. `limit` (default `200`)
2. `status` optional list of ticket statuses
3. `force` (default `false`) bypass `max_age_minutes` freshness skip
4. `max_age_minutes` (default `10`)
5. `stale_status_minutes` (default `120`)
6. `dry_run` (default `false`)

Result counters:

1. `processed`
2. `synced`
3. `escalated`
4. `stale_notified`
5. `skipped`
6. `failed`
7. `failures[]`
8. `escalations[]`
9. `proposed_actions[]` (for `dry_run=true`)
10. `dry_run_tickets[]` (for `dry_run=true`)
11. `ai_risk_summary`

## 11. Automation authentication for `/api/sla/run`

`/api/sla/run` can be called by:

1. Authenticated `admin`/`agent` JWT user.

Current implementation requires authenticated user access. `X-Automation-Secret` is reserved for explicit machine-auth endpoints such as `/api/notifications/system`, where it must match backend `N8N_INBOUND_SECRET`.

For production hardening, keep `N8N_INBOUND_SECRET` and `N8N_OUTBOUND_SECRET` separate and do not use n8n secrets as a fallback for normal authenticated routes.

Code reference:

1. `backend/app/core/deps.py`

## 12. n8n SLA alert workflow (current)

Existing workflow file:

1. `docs/n8n/workflow_sla_breach_alerting.json`

Current behavior:

1. Cron trigger every 15 minutes.
2. Calls `POST /api/sla/run` (`dry_run=false`).
3. Fetches `/api/tickets`.
4. Filters tickets with `sla_status in {breached, at_risk}`.
5. Sends email alerts (`Send SLA Email` node).
6. Logs errors via failure branch.

Important note:

1. This workflow sends email alerts and a best-effort Microsoft Teams message.
2. Teams delivery is optional and uses `TEAMS_WEBHOOK_URL` from the n8n environment.

## 13. Concrete SLA examples

Examples are provided under `docs/sla/examples/`:

1. `sla_run_dry_run_request.json`
2. `sla_run_dry_run_response.json`
3. `sla_run_live_response.json`
4. `sla_ticket_snapshot_response.json`
5. `ai_sla_risk_latest_response.json`
6. `sla_notifications_list_response.json`
7. `sla_alert_email_example.txt`

Quick API examples:

```bash
# Dry-run batch (no writes)
curl -X POST http://localhost:8000/api/sla/run \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d @docs/sla/examples/sla_run_dry_run_request.json
```

```bash
# Pull SLA-only notifications for current user
curl "http://localhost:8000/api/notifications?source=sla&unread_only=true" \
  -H "Authorization: Bearer <access_token>"
```

## 14. Frontend visibility points

SLA is surfaced in:

1. Ticket table SLA badge/hint (`ok`, `at_risk`, `breached`, etc.).
2. Ticket detail with AI SLA risk advisory panel.
3. Notification center filter by `source=sla`.
4. Dashboard/performance metrics including breach rates.

Code references:

1. `frontend/components/ticket-table.tsx`
2. `frontend/components/ticket-detail.tsx`
3. `frontend/app/notifications/page.tsx`
4. `frontend/lib/notifications-api.ts`
5. `frontend/lib/tickets-api.ts`

## 15. Operational checklist

Before enabling SLA automation in an environment:

1. Set Jira credentials and project context in `backend/.env`.
2. Set `N8N_INBOUND_SECRET` and `N8N_OUTBOUND_SECRET` in backend and n8n environments where relevant.
3. Confirm JWT-authenticated service access is used for `/api/sla/run` automation.
4. Run migrations:
   - `python -m alembic -c alembic.ini upgrade head`
5. Validate:
   - `POST /api/sla/run` with `dry_run=true`
   - `GET /api/sla/metrics`
   - `GET /api/notifications?source=sla`
