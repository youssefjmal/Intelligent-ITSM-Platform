# Backend n8n Integration Checklist

## 1. Auth and service identity

- [ ] Create a dedicated service account for n8n automation (for example: `n8n-bot@...`).
- [ ] Generate bearer token via `POST /api/auth/token` for that account.
- [ ] Ensure role/permissions allow:
  - `POST /api/sla/run`
  - `GET /api/tickets`
  - `PATCH /api/tickets/{ticket_id}/triage`
  - `GET /api/problems/{problem_id}`
  - `PATCH /api/problems/{problem_id}`
- [ ] Enforce least-privilege permissions for this user.
- [ ] Add token rotation policy (short lifetime, scheduled renewal).

## 2. Endpoint compatibility checks

- [ ] Confirm `POST /api/sla/run` accepts body `{ "dry_run": false }`.
- [ ] Confirm `GET /api/tickets` supports `sla_status=breached,at_risk`.
  - If not supported: add query parsing for list values.
- [ ] Confirm `PATCH /api/tickets/{ticket_id}/triage` accepts `priority=critical`.
  - If required by schema, include required fields (assignee/category/etc).
- [ ] Confirm `GET /api/tickets/{ticket_id}` exists for follow-up acknowledgment checks.
  - Needed by `workflow_critical_incident_escalator.json`.
- [ ] Confirm `GET /api/problems/{problem_id}` exists and returns full problem details.
- [ ] Confirm `PATCH /api/problems/{problem_id}` accepts notification metadata fields.
  - If not: add fields such as `notification_status`, `notification_channels`, `notification_actor`, `notification_sent_at`.

## 3. Audit traceability

- [ ] Ensure backend captures `X-Actor: system:n8n` from request headers in logs/audit records.
- [ ] Ensure ticket/problem update history stores the actor context.
- [ ] Keep `system:n8n` actor tag for all automation writes.

## 4. Webhooks and routing

- [ ] Register producer systems to call n8n webhooks:
  - `POST /webhook/critical-incident`
  - `POST /webhook/problem-detected`
- [ ] Validate webhook payload contract:
  - Critical incident: `{ ticket_id, priority, assignee_email, team_lead_email }`
  - Problem detected: `{ problem_id, title, affected_tickets_count, severity }`
- [ ] Add request validation on sender side (required fields and types).

## 5. Localhost and CORS considerations

- [ ] For n8n server-to-server calls to FastAPI (`localhost:5678` -> `localhost:8000`), CORS is not required.
- [ ] Keep CORS configured for browser clients only (frontend origin), not for internal token/webhook trust.
- [ ] If exposing services publicly (ngrok/reverse proxy), enforce HTTPS and IP/rate limits where possible.

## 6. Reliability and observability

- [ ] Add structured backend logs for n8n-triggered actions (ticket id/problem id, actor, endpoint, outcome).
- [ ] Add idempotency safeguards for repeated webhook deliveries.
- [ ] Add monitoring/alerts for failed n8n executions and backend 4xx/5xx spikes.
- [ ] Consider a dedicated backend endpoint to persist workflow failure logs from n8n.

## 7. Security hardening reminders

- [ ] Never store API tokens in workflow JSON directly; use `{{$env.ITSM_API_TOKEN}}`.
- [ ] Keep n8n env variables out of Git (`.env` excluded).
- [ ] Restrict SMTP/Teams credentials to minimum required channels.
- [ ] Review security headers and runtime guards in backend before production rollout.
