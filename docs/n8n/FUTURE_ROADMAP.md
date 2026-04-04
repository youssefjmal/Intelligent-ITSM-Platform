# n8n Automation — Future Roadmap

This document tracks planned improvements to the n8n automation layer: notification deduplication caching, Grafana monitoring, and longer-term workflow extensions.

---

## 1. Notification Delivery Caching (Redis)

### Problem

The current deduplication logic queries the PostgreSQL `notifications` table on every `/api/notifications/system` call:

```python
# backend/app/routers/notifications.py
rows = db.query(Notification.user_id).filter(
    Notification.dedupe_key == dedupe_key,
    Notification.created_at >= cutoff,
).all()
```

For high-frequency SLA polling (every 15 min × N at-risk tickets × M users), this becomes a hot read path that competes with user-facing queries.

### Proposed Solution

Introduce a **Redis SET** as a fast dedup cache with TTL equal to the dedup window (60 min):

```python
# Pseudo-code for cache-first dedup
cache_key = f"notif_dedupe:{dedupe_key}"
already_sent_users = redis_client.smembers(cache_key)

# Skip users already in the cache
new_users = target_users - already_sent_users

# After creating notifications:
redis_client.sadd(cache_key, *[str(u) for u in new_users])
redis_client.expire(cache_key, 3600)
```

### Implementation Steps

1. Add `redis[asyncio]` (or `redis`) to `backend/pyproject.toml`.
2. Add `REDIS_URL: str = "redis://localhost:6379/0"` to `backend/app/core/config.py`.
3. Create `backend/app/core/cache.py` — thin wrapper exposing `get_redis()` dependency.
4. Update `_dedupe_user_ids()` in `notifications.py` to check Redis first, fall back to DB on cache miss.
5. Populate cache after successful notification creation.
6. Add `redis` service to `docker-compose.yml`.
7. Update `backend/.env.example` with `REDIS_URL`.

### Expected Benefit

- Dedup check drops from ~5–20 ms (DB round-trip) to ~0.3 ms (Redis local).
- Reduces load on PostgreSQL during SLA batch runs.
- Cache automatically expires, no manual cleanup needed.

---

## 2. Grafana Monitoring Dashboard

### Problem

There is currently no visibility into:
- How many notifications are being created per event type per hour.
- What fraction are being deduplicated (suppressed).
- Whether n8n workflows are executing on schedule.
- Teams / email delivery failure rates.

### Proposed Architecture

```
PostgreSQL ──► prometheus_postgres_exporter ──► Prometheus ──► Grafana
n8n        ──► n8n built-in metrics endpoint ──► Prometheus
FastAPI    ──► /metrics (prometheus_fastapi_instrumentator) ──► Prometheus
```

### Panel Definitions

**Panel 1 — Notification creation rate (per event type)**
```promql
rate(notifications_created_total[5m])
```
Source: custom counter incremented in `notifications_service.py` on each `Notification` insert.

**Panel 2 — Deduplication suppression rate**
```promql
rate(notifications_deduplicated_total[5m]) / rate(notifications_attempted_total[5m])
```

**Panel 3 — n8n workflow execution success/failure**
Source: n8n's built-in `/metrics` endpoint (enable via `N8N_METRICS=true` env var).
```promql
n8n_workflow_executions_total{status="success"}
n8n_workflow_executions_total{status="error"}
```

**Panel 4 — Notification DB table size over time**
```promql
pg_stat_user_tables_n_live_tup{relname="notifications"}
```

**Panel 5 — Teams / email delivery error rate**
Requires structured n8n execution log parsing or a custom webhook log endpoint.

### Implementation Steps

1. Enable `N8N_METRICS=true` and `N8N_METRICS_PREFIX=n8n_` in n8n environment.
2. Add `prometheus-fastapi-instrumentator` to FastAPI (`backend/app/main.py`).
3. Add custom `Counter` metrics in `notifications_service.py`:
   - `notifications_created_total` (labels: `event_type`, `source`)
   - `notifications_deduplicated_total` (labels: `dedupe_key_prefix`)
4. Deploy `prom/prometheus` + `grafana/grafana` via `docker-compose.yml`.
5. Import the dashboard JSON (create in Grafana, export, commit to `docs/grafana/`).

### Grafana Alert Rules (Phase 2)

Once the dashboard is in place, add alert rules:

| Condition | Alert | Severity |
|---|---|---|
| `n8n_workflow_executions_total{status="error"}` > 3 in 15 min | n8n execution failures | warning |
| `rate(notifications_created_total[1h])` = 0 for > 2 hours | Notification pipeline silent | critical |
| `notifications_deduplicated_total / notifications_attempted_total` > 0.9 | Dedup rate anomaly (storm) | warning |

---

## 3. Workflow Extensions (Backlog)

### 3a. Ticket Resolved / SLA Met Notification

When a ticket transitions to `resolved` and its SLA was not breached, send a positive in-app notification to the assignee:

```
event_type: sla_resolved
severity: info
title: "SLA Met: TW-001 resolved in time"
dedupe_key: sla_resolved_<ticket_id>
```

n8n trigger: `POST /webhook/ticket-resolved` called from the FastAPI `tickets.py` service on status change.

### 3b. Agent Workload Digest

Daily cron (09:00 local) that queries `/api/tickets/agent-performance` and sends each agent a personal digest:
- Current open ticket count
- Tickets approaching SLA in the next 4 hours
- Any tickets unresponded for > 24 hours

Delivery: email + in-app notification with `digest` flag (so it shows in the digest section of the notification centre).

### 3c. Problem Closed Notification

Mirror of the Problem Launch Notifier — when a problem is resolved or closed, broadcast:
```
event_type: problem_resolved
severity: info
title: "Problem Resolved: PRB-42"
```

### 3d. Slack Integration (Parallel Channel)

Add a `Send Slack Message` node (n8n built-in) in parallel with the Teams node in each workflow, gated by `$env.SLACK_WEBHOOK_URL` being set. This allows teams that use Slack instead of / in addition to Teams to receive the same alerts without duplicating workflow logic.

---

## 4. Reliability Improvements

### Dead-letter Queue for Failed Notifications

When `POST /api/notifications/system` returns a non-2xx response inside n8n, the workflow currently logs and continues. A future improvement:

1. On failure, n8n writes the payload to a `notification_dlq` table (or Redis list).
2. A separate n8n cron workflow retries DLQ items every 5 minutes (up to 3 attempts).
3. After 3 failures, the item is moved to a `notification_failures` table for manual review.

### Idempotency Key on Webhook Triggers

Add `X-Idempotency-Key: <uuid>` support to the FastAPI webhook receiver so that n8n retries on timeout do not create duplicate workflows. The key would be stored in Redis for 10 minutes.

---

## Priority Ordering

| Item | Effort | Impact | Recommended Sprint |
|---|---|---|---|
| Redis dedup cache | Medium | High (performance) | Next sprint |
| Grafana dashboard | Medium | High (observability) | Next sprint |
| Ticket Resolved notification | Low | Medium | Next sprint |
| Agent workload digest | Medium | Medium | +2 sprints |
| Problem Closed notification | Low | Low | +2 sprints |
| Dead-letter queue | High | High (reliability) | +3 sprints |
| Graph API migration | High | Low (MessageCard still works) | +4 sprints |
| Slack integration | Low | Medium (org-dependent) | On demand |
