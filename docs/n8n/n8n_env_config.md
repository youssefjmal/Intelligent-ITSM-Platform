# n8n Environment Configuration

Set these variables in your n8n environment (for example in `.env`, Docker env, or n8n Cloud variables).

For your local mapping `5670:5678`, a ready local file was created at:

- `docs/n8n/.env`

Use:

```bash
docker run --rm -it \
  --name n8n \
  --env-file docs/n8n/.env \
  -p 5670:5678 \
  n8nio/n8n:latest
```

## Core backend integration

- `ITSM_BASE_URL`
  - Example: `http://localhost:8000`
- `ITSM_API_TOKEN`
  - Bearer token used in `Authorization: Bearer ...` for backend calls.
- `FRONTEND_BASE_URL`
  - Example: `http://localhost:3000`
  - Used to build problem/ticket deep links in notifications.

## SMTP / Email

- `SMTP_FROM`
  - Sender address used by n8n Email node.
- `SLA_ALERT_EMAIL_TO`
  - Comma-separated recipients for SLA breach alerts.
- `PROBLEM_ALERT_EMAIL_TO`
  - Comma-separated recipients for problem launch alerts.
- `ALERT_DEFAULT_EMAIL`
  - Optional fallback recipient when payload emails are missing.

Note: The Email node still requires an SMTP credential configured in n8n (host, port, user, password, TLS).

## Microsoft Teams

- `TEAMS_SLA_WEBHOOK_URL`
  - Incoming webhook URL used by SLA workflow.
- `TEAMS_ESCALATION_WEBHOOK_URL`
  - Incoming webhook URL for critical escalation alerts.
- `TEAMS_PROBLEM_WEBHOOK_URL`
  - Incoming webhook URL for problem launch adaptive cards.

## Optional operational variables

- `N8N_TIMEZONE`
  - Example: `Europe/Paris` or `UTC` (recommended for deterministic schedule behavior).
- `N8N_LOG_LEVEL`
  - Example: `info` / `debug` for troubleshooting workflow failures.

## Token acquisition reminder

Your backend supports bearer tokens through:

- `POST /api/auth/token`

Use a dedicated automation user (service account) to generate a token for `ITSM_API_TOKEN`, and rotate it regularly.
