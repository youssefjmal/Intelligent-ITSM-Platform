# Microsoft Teams Integration Plan

## Overview

The ITSM platform delivers real-time alerts to Microsoft Teams via **Incoming Webhook connectors** embedded in each n8n workflow. This document describes how the integration works today, how to extend it, and what a production-grade migration to the Graph API would look like.

---

## Current Architecture

### Connector Type

All three workflows use the **Office 365 Connector (MessageCard)** format, which requires only a single webhook URL per channel — no Azure AD app registration required.

```
n8n workflow ──POST──► Teams Incoming Webhook URL ──► Teams channel
```

The payload schema is `@type: MessageCard` with `@context: https://schema.org/extensions`.

### Per-Workflow Behaviour

| Workflow | Trigger | Teams node | Message colour |
|---|---|---|---|
| Critical Ticket Detector | Webhook (`POST /webhook/critical-ticket`) | `Send Teams Alert` | `C62828` (critical) / `EF6C00` (high) |
| Problem Launch Notifier | Webhook (`POST /webhook/problem-detected`) | `Send Teams Alert` | `C62828` / `EF6C00` based on priority |
| SLA Breach Alerting | Cron every 15 min | `Send SLA Teams Message` | `C62828` / `EF6C00` based on SLA state |

### Environment Variable

All three workflows read the Teams webhook URL from `$env.TEAMS_WEBHOOK_URL`. Set this in the n8n environment (or `.env` file when self-hosting):

```
TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/<your-connector-id>/IncomingWebhook/...
```

---

## Setting Up the Incoming Webhook

1. In Microsoft Teams, open the target channel → **Connectors** → **Incoming Webhook** → **Configure**.
2. Give the webhook a name (e.g. `ITSM Alerts`) and optionally upload an icon.
3. Copy the generated URL — this is your `TEAMS_WEBHOOK_URL`.
4. Paste the URL into n8n environment settings under `TEAMS_WEBHOOK_URL`.

Each workflow will immediately begin posting cards to that channel when events occur.

---

## MessageCard Payload Structure

The IIFE expression in each `jsonBody` builds the card dynamically:

```jsonc
{
  "@type": "MessageCard",
  "@context": "https://schema.org/extensions",
  "summary": "ITSM alert - <id>",
  "themeColor": "C62828",          // hex, no #
  "title": "Critical SLA Breach Ticket",
  "sections": [{
    "activityTitle": "<ticket-id> - <title>",
    "text": "[Open ticket](<url>)",
    "facts": [
      { "name": "Status",   "value": "open" },
      { "name": "Priority", "value": "Critical" },
      ...
    ],
    "markdown": true
  }],
  "potentialAction": [{
    "@type": "OpenUri",
    "name": "Open Ticket",
    "targets": [{ "os": "default", "uri": "<url>" }]
  }]
}
```

---

## Routing Alerts to Different Channels

To send different alert types to different Teams channels:

1. Add channel-specific environment variables in n8n:
   ```
   TEAMS_WEBHOOK_URL_SLA=https://...
   TEAMS_WEBHOOK_URL_PROBLEMS=https://...
   TEAMS_WEBHOOK_URL_CRITICAL=https://...
   ```

2. Update each workflow's Teams node URL expression:
   - Critical Ticket Detector: `$env.TEAMS_WEBHOOK_URL_CRITICAL || $env.TEAMS_WEBHOOK_URL`
   - Problem Launch Notifier: `$env.TEAMS_WEBHOOK_URL_PROBLEMS || $env.TEAMS_WEBHOOK_URL`
   - SLA Breach Alerting: `$env.TEAMS_WEBHOOK_URL_SLA || $env.TEAMS_WEBHOOK_URL`

This gives per-channel routing while keeping a single fallback URL for development.

---

## Production Migration: Graph API (Adaptive Cards)

The `MessageCard` format is **deprecated** by Microsoft in favour of **Adaptive Cards** delivered via the Graph API. The migration path when you need richer card interactions (inline replies, buttons that call back to your backend) is:

### Prerequisites

1. Register an **Azure AD application** with `ChannelMessage.Send` permission.
2. Obtain `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`.
3. Note the target `TEAMS_TEAM_ID` and `TEAMS_CHANNEL_ID`.

### n8n Workflow Changes

Replace each `httpRequest` Teams node with a two-node sequence:

**Node 1 — Get Access Token**
```
POST https://login.microsoftonline.com/{{$env.AZURE_TENANT_ID}}/oauth2/v2.0/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
&client_id={{$env.AZURE_CLIENT_ID}}
&client_secret={{$env.AZURE_CLIENT_SECRET}}
&scope=https://graph.microsoft.com/.default
```

**Node 2 — Send Adaptive Card**
```
POST https://graph.microsoft.com/v1.0/teams/{{$env.TEAMS_TEAM_ID}}/channels/{{$env.TEAMS_CHANNEL_ID}}/messages
Authorization: Bearer {{$node['Get Access Token'].json.access_token}}
Content-Type: application/json

{
  "body": {
    "contentType": "html",
    "content": "<attachment id=\"card1\"></attachment>"
  },
  "attachments": [{
    "id": "card1",
    "contentType": "application/vnd.microsoft.card.adaptive",
    "content": { ...Adaptive Card JSON... }
  }]
}
```

### Adaptive Card Template (Ticket Alert)

```json
{
  "type": "AdaptiveCard",
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.4",
  "body": [
    {
      "type": "TextBlock",
      "text": "🔴 Critical Ticket: TW-001",
      "weight": "Bolder",
      "size": "Medium"
    },
    {
      "type": "FactSet",
      "facts": [
        { "title": "Status",   "value": "open" },
        { "title": "Priority", "value": "Critical" },
        { "title": "Assignee", "value": "agent@example.com" }
      ]
    }
  ],
  "actions": [
    {
      "type": "Action.OpenUrl",
      "title": "Open Ticket",
      "url": "http://localhost:3000/tickets/TW-001"
    }
  ]
}
```

---

## Testing

### Local (without real Teams)

Set `TEAMS_WEBHOOK_URL` to a **Webhook.site** URL to inspect payloads without needing a Teams instance:

```
TEAMS_WEBHOOK_URL=https://webhook.site/<your-unique-id>
```

### Verifying a Real Delivery

After triggering a workflow manually in n8n:
1. Check the execution log of the Teams node — `status: 1` and response `"1"` (Teams returns the string `"1"` on success).
2. Confirm the card appears in the Teams channel within seconds.

### Error Handling

All three Teams nodes set `continueOnFail: true`. Failures are captured by the subsequent `Log Teams Delivery` / `Log Failure` code node and written to the n8n execution console log. No alert is silently dropped — if Teams fails the email has already been sent.

---

## Summary of Required Environment Variables

| Variable | Description | Required |
|---|---|---|
| `TEAMS_WEBHOOK_URL` | Default Incoming Webhook URL | Yes (for Teams alerts) |
| `TEAMS_WEBHOOK_URL_SLA` | SLA-specific channel (optional override) | No |
| `TEAMS_WEBHOOK_URL_PROBLEMS` | Problems-specific channel (optional override) | No |
| `TEAMS_WEBHOOK_URL_CRITICAL` | Critical tickets channel (optional override) | No |
| `FRONTEND_BASE_URL` | Base URL for deep-link generation in cards | Yes |
| `AZURE_TENANT_ID` | Azure AD tenant (Graph API migration only) | No |
| `AZURE_CLIENT_ID` | App registration ID (Graph API migration only) | No |
| `AZURE_CLIENT_SECRET` | App secret (Graph API migration only) | No |
| `TEAMS_TEAM_ID` | Graph API team ID (Graph API migration only) | No |
| `TEAMS_CHANNEL_ID` | Graph API channel ID (Graph API migration only) | No |
