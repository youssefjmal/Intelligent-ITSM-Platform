# n8n Workflow Guide

This folder contains the current n8n automation artifacts used with the ITSM platform.

The goal of this guide is to clarify:

1. which workflow files are present
2. what each workflow is responsible for
3. how n8n interacts with the FastAPI backend
4. which supporting docs to read before importing or editing workflows

## 1. Architectural role of n8n

n8n is used as an orchestration and notification layer.

It is not the source of truth for:

- tickets
- problems
- SLA state
- AI recommendations

The FastAPI backend remains the authoritative system for business state and audit logic.

High-level flow:

```text
event/webhook/schedule
-> n8n workflow
-> backend API call(s)
-> backend decides data/state changes
-> n8n sends notifications or follow-up actions
-> backend logs/audits the result when applicable
```

## 2. Workflow inventory

Primary workflow files currently present in this folder:

1. `workflow_critical_ticket_detector.json`
   - Detects or processes critical-ticket alert flows.
   - Typical purpose: fetch ticket data, build escalation payload, send notifications, log execution context.
2. `workflow_problem_launch_notifier.json`
   - Handles problem-launch notifications.
   - Typical purpose: fetch problem details, build alert payload, send email/Teams notification, log workflow outcome.
3. `workflow_sla_breach_alerting.json`
   - Handles SLA breach / at-risk alerting logic.
   - Typical purpose: react to SLA risk or breach signals and push notifications to the right operational channel.
4. `workflow_critical_incident_escalator.json`
   - Escalation-oriented critical-incident flow.
   - Typical purpose: drive follow-up escalation actions for already-identified critical incidents.

Supporting export/import variants:

1. `workflow_critical_ticket_detector.importable.json`
2. `workflow_problem_launch_notifier.import.json`
3. `all_workflows.json`

Supporting documentation:

1. `n8n_env_config.md`
2. `backend_n8n_integration_checklist.md`
3. `n8n_key.example.txt`

## 3. Workflow responsibilities

### 3.1 Critical ticket detector

Intent:

- respond when a ticket crosses a critical threshold
- gather authoritative ticket context from the backend
- notify stakeholders through configured channels

Typical backend interaction:

```text
incoming trigger/webhook
-> n8n extracts ticket identifier
-> n8n fetches backend ticket details
-> n8n builds notification payload
-> email / Teams / other channel send
-> optional execution log or callback
```

Use this when:

- the ticket itself is the main operational entity
- a fast escalation signal is needed

### 3.2 Problem launch notifier

Intent:

- notify teams when a problem record is launched or promoted
- give recipients direct problem context and deep links

Typical backend interaction:

```text
problem-detected trigger
-> n8n fetches problem details from backend
-> n8n formats title, severity, linked context
-> notification delivery
-> optional workflow log / audit callback
```

Use this when:

- the workflow should center on a recurring-incident / problem-management event
- the main audience is operations, leadership, or problem owners

### 3.3 SLA breach alerting

Intent:

- react to SLA breach or at-risk conditions
- notify the right recipients without replacing backend SLA ownership

Typical backend interaction:

```text
schedule or trigger
-> backend SLA evaluation or ticket fetch
-> n8n filters affected tickets
-> n8n sends alerts / escalations
-> backend remains source of truth for state and audit rules
```

Use this when:

- the focus is operational urgency and response timing
- the alert should be driven by SLA state rather than by generic ticket creation

### 3.4 Critical incident escalator

Intent:

- orchestrate a stronger response path for incidents already identified as critical
- add explicit escalation behavior on top of the basic detection/notification flow

Typical backend interaction:

```text
critical-incident trigger
-> fetch latest ticket state
-> build escalation decision payload
-> notify target channels / recipients
-> optional acknowledgement or backend update
```

Use this when:

- critical severity needs a separate escalation workflow
- operational responders need a stronger alert path than a simple notification

## 4. Backend integration model

The workflows should call backend APIs rather than duplicating backend logic inside n8n.

Recommended pattern:

1. n8n receives event or schedule input
2. n8n calls the backend to retrieve the latest entity state
3. backend remains authoritative for:
   - ticket/problem/SLA data
   - business rules
   - audit history
   - AI-derived recommendation or advisory state
4. n8n focuses on:
   - routing
   - notification formatting
   - cross-channel delivery
   - scheduled automation glue

## 5. AI relationship

n8n workflows do not replace the AI resolver or AI SLA advisory inside the backend.

The platform has separate AI responsibilities:

1. ticket/chat/recommendation resolver logic
   - handled in the backend AI retrieval + advisor services
2. SLA advisory logic
   - handled in backend SLA advisory services
3. notification orchestration
   - handled in n8n where appropriate

So the intended layering is:

```text
backend AI decides guidance
backend domain services decide state
n8n orchestrates delivery and automation
```

## 6. Environment and safety

Before editing or importing workflows:

1. read `n8n_env_config.md`
2. read `backend_n8n_integration_checklist.md`
3. keep secrets in local/runtime env only

Important safety notes:

1. Do not hardcode API keys, webhook URLs, SMTP credentials, or encryption keys in workflow JSON.
2. Treat local runtime artifacts in this folder as environment-specific, not as reusable source templates.
3. Prefer example/template files for documentation and onboarding.

## 7. Recommended reading order

If you are configuring n8n for the first time:

1. `README.md` (this file)
2. `n8n_env_config.md`
3. `backend_n8n_integration_checklist.md`
4. the specific workflow JSON you want to import

If you are debugging a workflow/backend interaction:

1. identify the workflow JSON file
2. confirm the backend endpoint contract
3. confirm actor/auth configuration
4. confirm notification channel credentials in n8n runtime
5. review backend logs / audit traces for the same event
