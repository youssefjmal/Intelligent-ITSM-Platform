# n8n Environment Configuration

Set these variables in your n8n environment (for example in `.env`, Docker env, or n8n Cloud variables).

## Secret handling (required)

- Keep real secrets in local env only; never commit them to git.
- Use `docs/n8n/n8n_key.example.txt` as a template only.
- Provide `N8N_ENCRYPTION_KEY` in `docs/n8n/.env` (local) or your runtime environment.
- Generate a key (PowerShell):

```powershell
[Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))
```

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
- `AUTOMATION_SECRET`
  - Shared secret sent in `X-Automation-Secret` for backend automation calls.
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

- `TEAMS_WEBHOOK_URL`
  - Incoming webhook URL used by the SLA, critical-ticket, and problem-notifier workflows.
  - Point this to the target Teams channel for alert delivery.
  - If you later want per-workflow channels, you can split this back into multiple env vars without changing backend logic.

## Optional operational variables

- `N8N_TIMEZONE`
  - Example: `Europe/Paris` or `UTC` (recommended for deterministic schedule behavior).
- `N8N_LOG_LEVEL`
  - Example: `info` / `debug` for troubleshooting workflow failures.

## Token acquisition reminder

Your backend supports bearer tokens through:

- `POST /api/auth/token`

Use a long random value for `AUTOMATION_SECRET` and keep it identical in backend `.env` and n8n environment variables.
