# Chatbot Backend Enhancements

## Overview

This update strengthens the ITSM copilot in two areas that were limiting production value:

1. Resolution guidance is now more specific and evidence-grounded.
2. Conversation continuity now works across follow-up questions without degrading deterministic routing.
3. Cause analysis is now more conservative about when a root cause is treated as confirmed versus only a supported hypothesis.

These changes were needed because the earlier chatbot flow could still return generic troubleshooting steps such as "check logs" or "verify configuration" even when the right incident family had already been selected. The chat layer also relied too heavily on short-lived ticket memory, which made follow-up prompts such as "Why?" or "Show me the second one" unreliable.

The new implementation keeps the resolver safe and operationally correct:

- recommendations stay inside the selected evidence family
- action steps must be tied to concrete ticket or retrieval signals
- cause-analysis checks stay scoped to the same selected family
- low-support hypotheses degrade to `insufficient_evidence` instead of sounding confirmed
- ambiguous follow-ups fall back safely instead of guessing
- older chat history is summarized instead of being dumped into every resolver call

## Architecture And Flow

### Previous behavior

The earlier chatbot flow worked, but it had two important weaknesses:

1. Ticket context reuse depended mainly on a narrow "last ticket" heuristic.
2. Recommended actions could still inherit generic phrasing from evidence snippets or formatter output.

Simplified previous flow:

```text
user message
-> intent detection
-> optional ticket lookup
-> retrieval / resolver
-> formatter / chat reply
```

### New behavior

The chat backend now adds a structured memory layer and a grounded action-building layer.

New flow:

```text
user message
-> explicit entity detection
-> structured chat session build
-> contextual reference resolution
-> deterministic routing
-> retrieval / resolver on the resolved entity
-> grounded action-step generation
-> safe payload formatting
-> structured session update
```

### Step-by-step flow

1. The current user message is checked for explicit ticket or problem identifiers.
2. A bounded chat session is built from recent turns.
3. Structured context is derived:
   - `last_ticket_id`
   - `last_ticket_list`
   - `active_topic`
   - `last_response_type`
   - `compared_ticket_ids`
   - recent turns
   - compact conversation summary
4. Contextual references such as `this ticket`, `the second one`, `the previous one`, and `Why?` are resolved safely from structured state.
5. Resolver-first guidance runs on the resolved ticket or problem.
6. Action steps are rebuilt from current ticket signals plus the selected coherent evidence cluster.
7. Generic actions are filtered or rewritten with subsystem-specific context.
8. The response payload exposes grounded action text, reason, and evidence references for the frontend.
9. Older turns are summarized so routing quality is preserved across longer conversations.

## Files Changed

| File | Purpose | What Changed | Why |
| --- | --- | --- | --- |
| `backend/app/services/ai/chat_session.py` | Structured chat memory and contextual entity resolution | Added chat session dataclasses and helpers for bounded history, summaries, list references, and comparison references | Follow-up prompts now work without relying on raw transcript replay |
| `backend/app/services/ai/orchestrator.py` | Main chat routing and response orchestration | Replaced the old single-ticket heuristic with structured session resolution, added comparison handling, and passed compact history context into resolver and formatter flows | Keeps routing deterministic while improving conversational continuity |
| `backend/app/services/ai/resolution_advisor.py` | Evidence-backed recommendation builder | Added operational signal extraction, grounded action-step construction, generic-action rejection, and stronger insufficient-evidence fallback rules | Makes recommendations specific, testable, and tied to evidence |
| `backend/app/services/ai/chat_payloads.py` | Structured API payload mapping | Added support for grounded action-step metadata with per-step reason and evidence | Preserves action grounding through the API layer |
| `backend/app/services/ai/resolver.py` | Shared resolver response assembly | Preserved advisor-authored workflow steps and added compact conversation summary handling | Prevents grounded steps from being flattened into generic output |
| `backend/app/services/ai/prompts.py` | Formatter and chat prompt rules | Added instructions to treat compact conversation context as authoritative and reject generic filler actions | Keeps formatter output aligned with deterministic backend constraints |
| `backend/tests/test_chat_session.py` | Session and history regression tests | Added coverage for bounded history, summary retention, list references, and previous-ticket references | Verifies safe memory behavior |
| `backend/tests/test_ai_routing_plan.py` | End-to-end chat routing tests | Added follow-up, positional reference, comparison, and grounded-action payload tests | Verifies chat continuity and structured response behavior |
| `backend/tests/test_resolution_advisor.py` | Resolver/advisor precision tests | Added tests for token-rotation specificity, generic-action filtering, and low-signal insufficient-evidence fallback | Verifies recommendation quality improvements |
| `.gitignore` | Repository safety rules | Added `.ops_backups/` to ignored local artifact paths | Prevents local backup dumps from being staged or pushed |

## Added vs Removed

### Newly Added

- `ChatSession` and `MessageTurn` session models
  - store bounded recent history, structured context, and compact summary data
  - added to support natural follow-ups without handing the full transcript to routing or retrieval
- Context resolution helpers
  - `build_chat_session(...)`
  - `resolve_contextual_reference(...)`
  - `resolve_comparison_targets(...)`
  - `build_relevant_history_context(...)`
  - added to resolve expressions like `this ticket`, `the second one`, and `compare it with the previous one`
- Grounded action-step helpers
  - `extract_ticket_operational_signals(...)`
  - `action_is_too_generic(...)`
  - `bind_action_to_evidence(...)`
  - `build_grounded_actions(...)`
  - `build_validation_from_actions(...)`
  - added to keep recommended actions specific and evidence-backed
- Cause-analysis calibration helpers
  - selected-family filtering for recommended checks and validation steps
  - conservative hypothesis support checks before returning a ranked cause-analysis payload
  - added so low-confidence root-cause statements degrade safely instead of sounding confirmed
- `GroundedActionStep`
  - carries `step`, `text`, `reason`, and `evidence`
  - added so the backend can preserve why each step exists
- New regression tests for history and action specificity
  - added to lock in the new behavior and protect against generic regressions

### Removed

- Removed the old "last ticket only" context reuse path as the primary follow-up strategy
  - replaced by structured session memory and reference resolution helpers
- Removed the assumption that generic extracted troubleshooting text is safe to reuse as-is
  - replaced by grounded action-step generation and generic-action rejection
- Removed dependence on replaying long raw history into every guidance path
  - replaced by compact structured context plus bounded recent turns

### Refactored

- Chat routing now resolves entities through session helpers before entering list/detail/guidance branches
  - behavior is improved, but explicit ticket IDs still take highest priority
- Resolver output shaping now preserves explicit workflow steps from the advisor
  - behavior is consistent with prior API contracts while keeping richer internals
- Prompt guidance was tightened
  - formatter output is still allowed, but it can no longer override resolver safety rules

## Behavior Impact

### What Improved

- Resolution advice is more specific and subsystem-aware.
- Follow-up questions reuse the correct ticket context more reliably.
- Comparison prompts work with the last two discussed tickets.
- Generic checklist steps are filtered out when they are not grounded.
- Weak or ambiguous evidence now falls back to insufficient evidence more cleanly.
- Cause-analysis cards distinguish between confirmed cause and supported hypothesis more explicitly.
- Similar-ticket no-match responses stay anchored to the source ticket in their summary.

### What Stayed The Same

- Explicit ticket IDs still override all conversational memory.
- Deterministic routing still takes priority over freeform chat behavior.
- Resolver-first guidance remains the primary path for ticket-specific troubleshooting.
- Existing response payload types remain intact.

### Edge Cases

- If the user refers to a ticket ambiguously and there is no reliable structured context, the chatbot should ask for clarification or fall back safely.
- If evidence is coherent but still weak, the chatbot may return a cautious low-confidence response instead of a longer action plan.

### Known Limitations

- Conversation summaries are intentionally compact and operational; they are not intended to preserve full natural-language nuance.
- Very long multi-entity threads may still require an explicit ticket reference for best clarity.
- Retrieval quality still depends on the quality of the indexed ticket, comment, and KB evidence already in the system.

## Safety And Data Hygiene

This change set was prepared with commit hygiene in mind.

- No secrets, API keys, webhook URLs, tokens, credentials, database URLs, or local environment files were added to the safe commit set.
- `.env` and `.env.*` remain ignored by repository policy.
- `.ops_backups/` was added to `.gitignore` to keep local backup dumps out of version control.
- Local logs, generated dumps, and machine-specific runtime artifacts were intentionally excluded from staging.

## Testing Guide

### Automated tests

Run the focused backend test set:

```powershell
pytest backend/tests/test_chat_session.py -q
pytest backend/tests/test_resolution_advisor.py -q
pytest backend/tests/test_ai_routing_plan.py -q
pytest backend/tests/test_ai_resolver.py -q
```

Optional compile check:

```powershell
python -m compileall backend/app/services/ai
```

### Manual verification

1. Open the chatbot and ask for a specific ticket.
2. Follow with short prompts such as `What is the status?`, `Why?`, or `What should I do next?`
3. Verify that the chatbot keeps the same ticket context.
4. Ask for comparison and list-position follow-ups.
5. Confirm that action steps mention the relevant subsystem and evidence rather than generic placeholders.
6. Confirm that ambiguous prompts without context do not invent a ticket or root cause.

## Example Test Prompts

### Single-ticket factual

- Prompt: `Show me details of TW-MOCK-019`
  - Expected: returns the TW-MOCK-019 detail view or structured ticket details payload
- Prompt: `What is the status of TW-MOCK-019?`
  - Expected: returns status for TW-MOCK-019 without drifting into another ticket

### Context follow-up

- Prompt sequence:
  - `Show me details of TW-MOCK-019`
  - `What is the status?`
  - `Why is this happening?`
  - `What should I do next?`
  - Expected: all follow-ups stay anchored to TW-MOCK-019 and reuse the active incident topic

### List plus positional reference

- Prompt sequence:
  - `Show high SLA tickets`
  - `Show me the second one`
  - Expected: the second ticket from the last returned list is resolved deterministically

### Recommendation specificity

- Prompt: `What should I do for TW-MOCK-019?`
  - Expected: actions mention token rotation, integration credential state, sync worker behavior, or manual sync validation
  - Expected: no export, dashboard, or unrelated remediation steps

### Cause analysis

- Prompt: `Why is this problem happening for TW-MOCK-020?`
  - Expected: returns ranked causes tied to retrieved evidence for TW-MOCK-020
  - Expected: if evidence is only partial, the payload clearly frames the top cause as a hypothesis rather than a confirmed root cause

### Insufficient evidence

- Prompt: `Why did this happen?`
  - Expected: if no context is available, the chatbot asks for enough context or returns a safe insufficient-evidence style answer

### Comparison

- Prompt sequence:
  - `Show TW-MOCK-019`
  - `Show TW-MOCK-025`
  - `Compare it with the previous one`
  - Expected: compares TW-MOCK-025 against TW-MOCK-019 using the last two mentioned tickets

## Reviewer Notes

This document is intentionally scoped to the chatbot/backend enhancement set only. It does not attempt to summarize unrelated local work currently present in the repository working tree.
