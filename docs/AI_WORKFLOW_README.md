# AI Workflow — Chatbot and Recommendation Engine

This document explains, step by step, how every AI feature in the platform works —
from the moment a user types a message or opens a ticket, to the final response on screen.

It is written to be fully self-contained. You do not need to read any source file
to understand the architecture. Every component is named, every path described,
and every decision explained with a real example.

---

## Table of Contents

1. [System map — what the AI does](#1-system-map)
2. [Chatbot pipeline — full walkthrough](#2-chatbot-pipeline)
   - 2.1 Entry point and session hydration
   - 2.2 Intent detection (Stage 1: rules)
   - 2.3 Intent detection (Stage 2: LLM fallback)
   - 2.4 Routing plan
   - 2.5 Deterministic shortcut paths
   - 2.6 General LLM path
   - 2.7 Guidance / troubleshooting path
3. [Recommendation pipeline — full walkthrough](#3-recommendation-pipeline)
   - 3.1 Entry point
   - 3.2 unified_retrieve — evidence gathering
   - 3.3 Scoring: coherence, context, and conflict detection
   - 3.4 Cluster selection
   - 3.5 build_resolution_advice — synthesis
   - 3.6 Display modes and trust hierarchy
   - 3.7 LLM general advisory fallback
4. [AI ticket summarization](#4-ai-ticket-summarization)
5. [SLA advisory panel](#5-sla-advisory-panel)
6. [User stories with detailed examples](#6-user-stories-with-detailed-examples)
7. [Key constants and thresholds](#7-key-constants-and-thresholds)
8. [File map — where everything lives](#8-file-map)

---

## 1. System Map

The AI layer sits between the FastAPI routers and the database/LLM.
It is made of three independent pipelines that share some utilities:

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                    │
│  ticket-chatbot.tsx  ·  ticket-detail.tsx  ·  recommendations.tsx │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API calls
┌──────────────────────────▼──────────────────────────────────┐
│                    FastAPI Routers                           │
│  /api/ai/chat  ·  /api/tickets/{id}/recommendations         │
│  /api/tickets/{id}/summary  ·  /api/sla/{id}/advisory       │
└────────┬─────────────────┬──────────────────┬───────────────┘
         │                 │                  │
    ┌────▼────┐      ┌─────▼──────┐    ┌──────▼──────┐
    │Chatbot  │      │Recommenda- │    │SLA Advisory │
    │Pipeline │      │tion Pipeline│    │Pipeline     │
    └────┬────┘      └─────┬──────┘    └──────┬──────┘
         │                 │                  │
    ┌────▼──────────────────▼──────────────────▼─────┐
    │              Shared AI utilities                │
    │  unified_retrieve  ·  calibration  ·  taxonomy  │
    │  llm (ollama_generate)  ·  embeddings           │
    └─────────────────────────────────────────────────┘
```

The chatbot and the recommendation page use the **same underlying retrieval
and scoring engine** (`unified_retrieve` + `build_resolution_advice`).
The SLA advisory is a separate deterministic-first pipeline.

---

## 2. Chatbot Pipeline

### Entry point

**File:** `backend/app/routers/ai.py` → `POST /api/ai/chat`
**Main orchestrator:** `backend/app/services/ai/orchestrator.py` → `handle_chat()`

A `ChatRequest` arrives containing:
- `user_id` — who is asking
- `question` — the raw user message (EN or FR)
- `conversation_history` — previous messages in the session
- optional `create_requested` flag (UI "create ticket" button)

---

### 2.1 Session hydration

Before any detection, the system builds a `ChatSession` object:

```
build_chat_session(conversation_history)
  → ChatSession {
      last_ticket_id: "TW-MOCK-023"   # last ticket mentioned
      last_problem_id: "PB-MOCK-01"   # last problem mentioned
      last_problem_list: ["PB-MOCK-01", "PB-MOCK-02"]  # last listed problems
    }
```

**File:** `backend/app/services/ai/chat_session.py`

This lets follow-up questions like *"tell me more about the first one"* be resolved
against the prior turn without re-querying the user.

`resolve_contextual_reference()` handles phrases like:
- "that ticket" → returns `last_ticket_id`
- "the first problem" → resolves index 0 of `last_problem_list`
- "the same issue" → returns last-referenced entity

---

### 2.2 Intent detection — Stage 1: rules

**File:** `backend/app/services/ai/intents.py` → `detect_intent_with_confidence()`

The normalized message is checked against keyword lists from
`backend/app/services/ai/conversation_policy.py`.

**Priority order (highest checked first):**

| Priority | Intent | Example trigger |
|----------|--------|-----------------|
| 1 | `problem_detail` | message contains a PB-* ID, or "detail about this problem" |
| 2 | `problem_drill_down` | "show tickets linked to this problem" |
| 3 | `problem_listing` | "show me all open problems" |
| 4 | `recommendation_listing` | "what are the recommendations for TW-023" |
| 5 | `create_ticket` | "create a new ticket" |
| 6 | `recent_ticket` | "show my recent tickets" |
| 7 | `most_used_tickets` | "most common tickets this week" |
| 8 | `weekly_summary` | "give me the weekly summary" |
| 9 | `critical_tickets` | "show critical tickets" |
| 10 | `recurring_solutions` | "what fixes recurring issues" |
| 11 | `data_query` | "how many tickets are open" |
| 12 | `general` (guidance) | "how do I fix TW-023" |
| 13 | `general` (fallback) | everything else |

**Single-word keywords use regex `\b` word-boundary matching** to prevent false
positives. For example, the keyword `"open"` must not match `"open_source_vulnerability"`.
Multi-word phrases use plain substring matching because their specificity eliminates
accidental collisions.

Confidence levels returned:
- `high` — a strong rule matched
- `medium` — a softer heuristic matched
- `low` — no rule matched; proceed to Stage 2

---

### 2.3 Intent detection — Stage 2: LLM fallback

**Only fires when Stage 1 returns `low` confidence.**

A minimal prompt is sent to the local LLM (Ollama):

```
Classify the user request into exactly one label:
- guidance   (troubleshooting, fixing, recommendations)
- information (ticket details, status, show/list)
- analytics  (metrics, counts, KPI, stats)
- creation   (create or draft a ticket)

User message: <message>
Return ONLY one label.
```

The label is mapped back to a `ChatIntent`:
- `"creation"` → `ChatIntent.create_ticket`
- `"information"` or `"analytics"` → `ChatIntent.data_query`
- `"guidance"` or anything else → `ChatIntent.general`

The confidence returned is always `low` even if the LLM responds clearly.
This prevents overconfident routing on ambiguous messages.

---

### 2.4 Routing plan

**File:** `orchestrator.py` → `build_routing_plan()`

Based on the intent, a `RoutingPlan` is created. It specifies:
- `name` — which handler to invoke (e.g. `"shortcut_problems"`)
- `use_llm` — whether the LLM will be called
- `use_kb` — whether the Jira KB will be injected into the prompt

```
Intent                  → RoutingPlan name
─────────────────────────────────────────
problem_detail          → shortcut_problem_detail      (no LLM, no KB)
problem_listing         → shortcut_problems             (no LLM, no KB)
problem_drill_down      → shortcut_problem_linked_tickets (no LLM, no KB)
recommendation_listing  → shortcut_recommendations      (no LLM, no KB)
most_used_tickets       → shortcut_most_used_tickets    (no LLM, no KB)
weekly_summary          → shortcut_weekly_summary       (no LLM, no KB)
critical_tickets        → shortcut_critical_tickets     (no LLM, no KB)
recurring_solutions     → shortcut_recurring_solutions  (no LLM, no KB)
data_query              → structured_data_query         (no LLM, no KB)
create_ticket           → forced_create_ticket          (LLM + KB)
general (guidance)      → general_llm                  (LLM + KB)
general (fallback)      → general_llm                  (LLM + KB)
```

Deterministic shortcuts bypass both the LLM and KB entirely.
They are fast, auditable, and never hallucinate.

---

### 2.5 Deterministic shortcut paths

These handlers run pure database queries and format the result directly into a
structured `ChatResponse`. No LLM call is made.

#### `shortcut_problems`

Triggered by: *"show me all open problems"*, *"list problems"*, *"problèmes en cours"*

1. Extract status filter via `extract_status_filter()` using `STATUS_KEYWORD_MAP`
   (e.g. "open problems" → filter: `"open"`, "known errors" → `"known_error"`)
2. Query `Problem` table with optional status filter
3. Format into `build_problem_list_payload()` → list of cards with title, status, severity, linked ticket count
4. Store problem IDs in `ChatSession.last_problem_list` for follow-up resolution

#### `shortcut_problem_detail`

Triggered by: message containing a `PB-*` ID, or *"detail about this problem"*

1. Extract problem ID from message using `extract_problem_id()` or resolve
   from session context via `resolve_problem_contextual_reference()`
2. Query `Problem` + its linked tickets from DB
3. Format into `build_problem_detail_payload()` → single card with full description,
   status, severity, workaround, linked ticket list

#### `shortcut_problem_linked_tickets`

Triggered by: *"show tickets linked to this problem"*, *"drill down"*

1. Resolve problem ID from message or session (`last_problem_id`)
2. Query linked tickets ordered by priority
3. Return ticket list with status badges

#### `shortcut_recommendations`

Triggered by: *"what are the recommendations for TW-023"*, *"AI advice"*

1. Extract ticket ID from message
2. Load the pre-computed `AIResolutionAdvice` for the ticket from DB
3. Format top N (max `MAX_CHAT_RECOMMENDATIONS = 5`) into response cards
4. Each card includes `recommended_action`, `confidence`, `evidence_sources`

#### Other shortcuts (ticket-focused)

- `shortcut_recent_ticket` — returns last N tickets by `created_at`
- `shortcut_critical_tickets` — returns tickets where `priority = critical`
- `shortcut_most_used_tickets` — returns tickets by frequency/volume
- `shortcut_weekly_summary` — aggregates ticket stats for the past 7 days
- `shortcut_recurring_solutions` — surfaces tickets with repeated fixes

---

### 2.6 General LLM path

Triggered for: `general` intent → `general_llm` routing plan

This path handles natural-language questions that did not match any shortcut.
Example: *"why does the payroll export fail on the 28th of every month?"*

Steps:

1. **Jira KB lookup** (`build_jira_knowledge_block()`)
   The Jira KB is a pre-built in-memory snapshot of Jira issue titles, descriptions,
   and comments with precomputed embeddings. A semantic search runs against the
   question and the top matching passages are selected. This block is injected
   into the LLM prompt as grounding context.

   > **What is the Jira KB?**
   > It is not the local PostgreSQL database. It is an in-memory index built from
   > a snapshot of Jira Service Management content (tickets, comments). The snapshot
   > is periodically refreshed by `backend/scripts/refresh_jira_kb_index.py`.
   > It enables the chatbot to answer questions about Jira issues that are not
   > mirrored locally.

2. **Conversation history** is compressed to the most relevant prior messages
   using `build_relevant_history_context()` to avoid token overflow.

3. **Prompt construction** (`build_chat_grounded_prompt()` or `build_chat_prompt()`)
   The LLM prompt includes:
   - System persona (ITSM assistant)
   - Jira KB context (if available)
   - Recent conversation history
   - The current question

4. **LLM call** (`ollama_generate()`)
   The local Ollama instance generates a text response.

5. **Response wrapping** — the text is returned as a plain `ChatResponse` with
   `response_type = "text"`.

---

### 2.7 Guidance / troubleshooting path

Triggered when: `general` intent + the message is classified as a **guidance** request
(e.g. *"how do I fix TW-023"*, *"what should I do about the SLA breach on TW-017"*)

This is the most complex path because it combines retrieval + evidence + LLM.

```
User: "how do I fix TW-023?"
         │
         ▼
1. Resolve ticket context
   → extract ticket ID "TW-023" from message
   → load Ticket from DB (title, description, category, priority)
         │
         ▼
2. unified_retrieve(db, query=ticket_context, top_k=5)
   → (see Section 3 for full detail)
   → returns: list[RetrievedEvidence] ranked by coherence score
         │
         ▼
3. build_resolution_advice(ticket, evidence_list)
   → (see Section 3)
   → returns: AIResolutionAdvice with display_mode, recommended_action, etc.
         │
         ▼
4. If guidance confidence is >= GUIDANCE_CONFIDENCE_THRESHOLD (0.6):
   → return structured recommendation payload
   Else:
   → fall through to LLM general path with retrieval context injected
```

The guidance path re-uses the same retrieval/advisor engine as the
`/recommendations` endpoint — the chatbot and the recommendations page
produce the same quality of advice.

---

## 3. Recommendation Pipeline

This pipeline is triggered by:
- `GET /api/tickets/{ticket_id}/recommendations`
- The guidance path in the chatbot (Section 2.7)
- Problem-linked ticket analysis

**Files:**
- `backend/app/services/ai/retrieval.py`
- `backend/app/services/ai/resolution_advisor.py`
- `backend/app/services/ai/resolver.py`
- `backend/app/services/recommendations.py`

---

### 3.1 Entry point

```python
resolve_ticket_advice(db, ticket, top_k=5)
  → ResolverOutput {
      advice: AIResolutionAdvice
      evidence: list[RetrievedEvidence]
      source_label: str
    }
```

Before the incident resolver runs, the platform now checks whether the ticket is
a planned service-request workflow. When the ticket is structurally a service
request and matches a supported fulfillment family such as
`account_provisioning`, `access_provisioning`, `credential_rotation`,
`scheduled_maintenance`, `notification_distribution_change`, or
`integration_configuration`, the backend returns
`display_mode = "service_request"` instead of incident diagnosis. This decision
is now shared by chat guidance, ticket detail AI recommendations, and the
recommendations page.

The service-request gate is now profile-first for planned workflows. If the
coarse classifier returns `ticket_type = None` or lands on a domain category
such as `application`/`hardware`, a strong fulfillment profile can still route
the ticket into `service_request` mode. Explicit `incident` classification still
blocks that bypass so real failures stay on the resolver/RAG path.

Service requests no longer borrow the incident topic map directly. The backend
builds a dedicated request profile from:
- operation signals (`create`, `grant`, `rotate`, `schedule`, `update`, `remove`)
- resource signals (`account`, `access`, `credential`, `integration`, `distribution_rule`, `task`, `device`, `workspace`)
- governance signals (`approval`, `owner`, `cadence`, `policy`, `validation`)
- fulfillment-family hints such as `device_provisioning` and `reporting_workspace_setup` in addition to the families above

That profile is then used for:
- deciding whether service-request mode is valid at all
- choosing the runbook family for the recommendation card
- ranking similar tickets for service-request pages so provisioning requests do not drift toward unrelated recurring-task workflows

Separately, Jira category mapping now prefers text-grounded domain inference over
generic issue-type fallback. That means tickets with generic Jira issue types
such as `Service Request` can still land in a real domain category like
`hardware` or `application` when the summary/description clearly support it.

---

### 3.2 unified_retrieve — evidence gathering

`unified_retrieve(db, query=..., visible_tickets=[], top_k=5)`

This function gathers evidence from **five sources in priority order**:

| Priority | Source | How matched |
|----------|--------|-------------|
| 1 | Resolved tickets | Semantic embedding similarity + lexical overlap |
| 2 | Similar open tickets | Same signals, penalized for unresolved status |
| 3 | KB articles | Semantic search against embedded KB corpus |
| 4 | Comment-based fixes | Comments on resolved tickets with action/outcome terms |
| 5 | Related problems | Problem-ticket association table |

For each candidate, a `RetrievedEvidence` object is built with:
- `text` — the resolution step or KB passage
- `evidence_type` — one of the 5 source types above
- `base_score` — raw embedding cosine similarity
- `context_score` — query-aware relevance score (see 3.3)
- `coherence_score` — combined final score after all bonuses/penalties
- `feedback_bonus` — positive feedback from prior user votes boosts this score

**Feedback loop:** If users have previously voted "helpful" on a resolution from
ticket T, that ticket's `feedback_bonus` is added to its coherence score in future
retrievals. This means the system gets more precise over time without retraining.

Grounded-classification alignment:
- the classifier no longer treats raw semantic Jira hits as trusted metadata votes by default
- semantic matches are first passed through the same grounded issue-family filtering used by retrieval
- comment evidence is attached only after the Jira issue family itself has been grounded
- this keeps ticket `type` and `category` aligned with the same evidence contract used for recommendations

Contrast-aware retrieval:
- query parsing now extracts `negative_domains`, `negative_topics`, and `negative_terms`
  when the ticket describes a false-positive family
- those signals penalize or reject candidates that only align with the contrasted family
- if a strong semantic Jira issue appears mainly as contrasted evidence, grounded issue
  matching can mark the retrieval as conflicted and suppress strong-match promotion

---

### 3.3 Scoring: coherence, context, and conflict detection

Each piece of evidence passes through two scoring functions:

#### `score_context_relevance()`

Measures how well the evidence **topic** matches the query topic:

```
context_score =
  title_overlap   × 0.28
+ focus_overlap   × 0.24
+ strong_overlap  × 0.20
+ lexical_overlap × 0.14
+ topic_overlap   × 0.08
+ phrase bonuses  (up to +0.12)
- generic lexical penalty  (-0.06 if mostly generic words)
- topic mismatch penalty   (-0.24 if topic tags differ)
- domain mismatch penalty  (-0.18 if IT domain differs)
```

A piece of evidence about *email relay* will receive a heavy `topic_mismatch_penalty`
against a query about *CRM token rotation*. This prevents cross-domain contamination.

#### `score_candidate_coherence()`

Combines the embedding score, context score, and evidence-type weight:

```
coherence =
  base_score   × 0.22  (raw embedding similarity)
+ context_score × 0.24
+ title_overlap × 0.12
+ lexical_overlap × 0.12
+ strong_overlap × 0.18
+ topic_overlap × 0.08
+ dominant topic bonus   (+0.12 if dominant topic matches)
+ domain bonus           (+0.06)
+ exact term bonus       (+0.03 to +0.06)
- generic_only_overlap   (-0.28 if only stopwords match)
- topic_mismatch         (-0.34)
- domain_mismatch        (-0.24)
- weak_signal_cap        (caps at 0.24 if signal is weak)
```

Evidence types also carry a **cluster weight multiplier**:
- resolved ticket: 1.0 (highest trust)
- similar ticket: 0.92
- comment: 0.88
- KB article: 0.82
- related problem: 0.78

---

### 3.4 Cluster selection

`cluster_evidence()` + `select_primary_cluster()`

After scoring, evidence items are grouped into **clusters** — sets of items
that share the same dominant topic and proposed fix direction.

The primary cluster is chosen by:

1. **Anchored cluster check** (top item coherence ≥ 0.68, cluster score ≥ 0.38)
   → the cluster is considered anchored and reliable
2. **Strong cluster check** (top item coherence ≥ 0.82, cluster score ≥ 0.70)
   → high confidence, minimal filtering needed
3. **Conflict detection** — if a second cluster is close in score (within 0.14)
   and both have medium-high coherence, the advice is flagged as conflicted
   and confidence is reduced

If no cluster meets minimum thresholds, the system does not fabricate evidence —
it falls through to `no_strong_match` or the LLM advisory fallback.

The confidence exposed by retrieval is now consensus-aware:
- one strong row is not enough by itself
- the system blends raw hit strength with cluster coherence/support
- if top evidence families conflict, confidence is capped to the low band
- mixed-family evidence therefore degrades into cautious diagnostic or manual-triage behavior instead of a confident wrong-family answer

---

### 3.5 build_resolution_advice — synthesis

`build_resolution_advice(ticket, evidence_cluster)` → `AIResolutionAdvice`

This function synthesizes the selected cluster into a structured recommendation:

**Step 1 — Action selection**
Picks the recommended action text from the highest-coherence evidence item.
Filters out actions with `action_relevance_score < 0.22` (hard floor: 0.18).

**Step 2 — Confidence scoring**
```
confidence_base = evidence_type_weight × coherence_score
+ semantic bonus (capped at +0.14)
+ lexical bonus  (capped at +0.12)
+ anchor bonus   (+0.06 if cluster is anchored)
+ action bonus   (capped at +0.07)
+ support bonus  (capped at +0.08 per supporting item, step 0.04)
+ agreement bonus (+0.10 if supporting items agree)
- tentative penalty (-0.25 if cluster is weak)
- domain mismatch  (-0.40)
- topic mismatch   (-0.34)
- weak lexical     (-0.16 if lexical signal is poor)
```

**Step 3 — Root cause confirmation**
The `probable_root_cause` field is set only if at least one piece of supporting
evidence has a coherence score ≥ 0.44 AND topic overlap ≥ 0.14. Otherwise it
remains null rather than guessing.

**Step 4 — Next best actions**
Up to 3 alternative actions are selected from non-primary cluster items with
coherence ≥ 0.42.

**Step 5 — Display mode assignment**
See Section 3.6.

**Output fields:**

| Field | Description |
|-------|-------------|
| `recommended_action` | The top suggested fix step |
| `reasoning` | Why this action was chosen |
| `evidence_sources` | List of source tickets/articles |
| `probable_root_cause` | Root cause if evidence supports it |
| `confidence` | Float 0.0–1.0 |
| `confidence_band` | `"high"` / `"medium"` / `"low"` |
| `display_mode` | See Section 3.6 |
| `next_best_actions` | Alternative steps |
| `incident_cluster` | Cluster signature |
| `impact_summary` | How many similar incidents found |
| `action_relevance_score` | How well the action matches the ticket |
| `filtered_weak_match` | True if a match was found but filtered |
| `source_label` | How retrieval was performed |
| `match_summary` | Human-readable summary of evidence |
| `llm_general_advisory` | Set when display_mode is llm_general_knowledge |
| `knowledge_source` | Set to "llm_general_knowledge" for advisory mode |

---

### 3.6 Display modes and trust hierarchy

The `display_mode` field controls how the frontend renders the card.
The trust hierarchy from highest to lowest:

```
evidence_action        ──┐ Strong evidence-backed fix.
                          │ Green styling. Apply button shown.
                          │ confidence ≥ 0.52 (medium band)
tentative_diagnostic   ──┤ Weak or conflicted evidence.
                          │ Yellow/amber styling. Apply button shown.
                          │ Safe diagnostic step, not a definitive fix.
service_request        ──┤ Planned fulfillment workflow.
                          │ Sky/blue workflow styling.
                          │ No root-cause framing; runbook-style next steps only.
llm_general_knowledge  ──┤ No local evidence. LLM general IT knowledge.
                          │ Blue/info styling. No Apply button.
                          │ confidence fixed at 0.25.
no_strong_match        ──┘ No safe advice can be given.
                            Grey/muted styling. Shows "no match" message.
```

The `filtered_weak_match = true` flag means the system found something but
deliberately suppressed it because the relevance was too low. This is intentional:
showing a wrong answer is worse than showing no answer.

---

### 3.7 LLM general advisory fallback

When `display_mode` is `no_strong_match` AND the local LLM is available, the
system makes one more attempt using general IT knowledge:

**File:** `backend/app/services/ai/resolution_advisor.py` → `build_llm_general_advisory()`

The LLM is given the ticket title and description and asked to produce:
- `probable_causes` — list of likely root causes based on general IT knowledge
- `suggested_checks` — diagnostic steps to perform next
- `escalation_hint` — when to escalate to a specialist

If the LLM succeeds within `LLM_GENERAL_ADVISORY_TIMEOUT_SECONDS = 8` seconds,
`display_mode` is promoted from `no_strong_match` to `llm_general_knowledge`.
If it times out or fails, the card stays as `no_strong_match`.

The frontend **must never show an Apply button** on `llm_general_knowledge` cards.
The advice is general IT knowledge, not validated against this environment.

---

## 4. AI Ticket Summarization

**File:** `backend/app/services/ai/summarization.py`
**Endpoint:** `GET /api/tickets/{ticket_id}/summary`

When a user opens a ticket detail page, the frontend requests an AI-generated summary.

### Flow

```
1. Check cache: if ticket.summary_generated_at is within 60 minutes → return cached text

2. Build RAG context:
   unified_retrieve(db, query=ticket_text, top_k=5)
   → select top 3 resolved similar tickets as context examples

3. Build LLM prompt:
   "Summarize this ITSM ticket in 2-3 sentences.
    Include: category, probable cause if known, current status, suggested next step.
    Context from similar resolved tickets: <RAG context>"

4. Call ollama_generate() → parse response text

5. Truncate to SUMMARY_MAX_LENGTH_CHARS = 500 characters

6. Persist to ticket.ai_summary + ticket.summary_generated_at in DB

7. Return SummaryResult { summary, generated_at, cached }
```

### Cache invalidation

`invalidate_ticket_summary()` clears `summary_generated_at` (but keeps the
stale text as fallback). It is called automatically when:
- Ticket status changes
- Ticket description or triage fields are updated

The next summary request after invalidation triggers a fresh LLM generation.

---

## 5. SLA Advisory Panel

**File:** `backend/app/services/ai/ai_sla_risk.py`
**Endpoint:** `GET /api/sla/{ticket_id}/advisory`

Every ticket detail page shows an SLA advisory panel. It is always deterministic-first.

### Flow

```
1. Compute deterministic risk score:
   elapsed_ratio = (now - ticket.created_at) / ticket.sla_deadline
   priority_factor = AI_SLA_PRIORITY_FACTORS[ticket.priority]
                    (low=0.2, medium=0.45, high=0.72, critical=1.0)
   risk_score = elapsed_ratio × priority_factor × inactivity_factor

2. Assign band:
   risk_score ≥ 0.80 → "critical"
   risk_score ≥ 0.60 → "high"
   risk_score ≥ 0.30 → "medium"
   risk_score < 0.30 → "low"

3. Generate recommended_actions from rule templates
   (e.g. "Escalate immediately — SLA at 90% elapsed")

4. If persisted AI evaluation exists (from prior LLM run):
   blend: deterministic × 0.68 + AI × 0.32
   advisory_mode = "hybrid"
   Else:
   advisory_mode = "deterministic"

5. Return advisory payload with:
   risk_score, band, confidence, reasoning, recommended_actions,
   advisory_mode, sla_elapsed_ratio, time_consumed_percent
```

---

## 6. User Stories with Detailed Examples

---

### Story 1 — Agent asks about a specific ticket

> **User:** "How do I fix TW-MOCK-023?"

**Step-by-step trace:**

1. `detect_intent("how do I fix TW-MOCK-023?")`
   → `_has_explicit_guidance_keyword("fix")` → `True`
   → intent: `ChatIntent.general`, confidence: `high`, is_guidance: `True`

2. `build_routing_plan` → `RoutingPlan(name="general_llm", use_llm=True, use_kb=True)`

3. `_supports_resolver_first_guidance(pattern="HOW_TO_FIX", plan=general_llm)` → `True`

4. `resolve_ticket_advice(db, ticket=TW-MOCK-023, top_k=5)`
   - `unified_retrieve`:
     - Embedding of "certificate renewal relay server unreachable" (ticket description)
     - Top semantic match: TW-MOCK-014 (resolved, "relay certificate expired") → coherence 0.81
     - Second match: TW-MOCK-031 (resolved, "certificate rotation relay") → coherence 0.74
     - KB article: "How to renew an expired relay certificate" → coherence 0.68
   - `cluster_evidence`: two items cluster around topic "relay_certificate"
   - `select_primary_cluster`: anchored (top coherence 0.81 ≥ 0.68) ✓
   - `build_resolution_advice`:
     - `recommended_action`: "Renew the relay certificate and restart the mail service"
     - `confidence`: 0.84 → band: `"high"`
     - `display_mode`: `"evidence_action"`
     - `evidence_sources`: [TW-MOCK-014, TW-MOCK-031, KB article]
     - `next_best_actions`: ["Check certificate expiry with openssl", "Verify relay port 587"]

5. Guidance confidence (0.84) ≥ `GUIDANCE_CONFIDENCE_THRESHOLD` (0.6) → structured card returned

**What the user sees:**
A chat card with a green confidence bar at `high`, the recommended action,
and 3 evidence sources they can click.

---

### Story 2 — Agent asks about an unfamiliar issue

> **User:** "The billing integration keeps failing with a 429 error on the 1st of every month"

1. `detect_intent(...)` → `ChatIntent.general`, guidance → `True`

2. `unified_retrieve`:
   - Embedding of billing/API rate limit
   - No resolved tickets match with coherence ≥ 0.42
   - No KB articles match with coherence ≥ 0.42
   - Best candidate: coherence 0.31 → filtered (below support_min_coherence)
   - `filtered_weak_match = True`

3. `build_resolution_advice`:
   - No primary cluster selected
   - `display_mode`: `"no_strong_match"` initially

4. `build_llm_general_advisory(ticket_context)` called within 8-second timeout
   - LLM responds with:
     ```
     probable_causes: ["API rate limiting (429 = Too Many Requests)",
                       "Scheduled job sending bulk requests simultaneously"]
     suggested_checks: ["Check billing API rate limit docs",
                        "Add exponential backoff to the job",
                        "Stagger job execution by 5 minutes"]
     escalation_hint: "Escalate if rate limit is a paid-tier constraint"
     ```
   - `display_mode` promoted to `"llm_general_knowledge"`
   - `confidence`: fixed at 0.25

**What the user sees:**
A blue/info card labeled "General IT Knowledge" with probable causes and checks.
No Apply button. A note that this is LLM advisory, not validated evidence.

---

### Story 3 — Agent lists problems and drills down

> **User:** "show me open problems"

1. Intent: `problem_listing` (high) → `shortcut_problems`
2. `extract_status_filter("show me open problems")` → `"open"`
3. DB query: `Problem.status == "open"` → [PB-MOCK-01, PB-MOCK-02]
4. `build_problem_list_payload()` → 2 cards
5. `ChatSession.last_problem_list` = ["PB-MOCK-01", "PB-MOCK-02"]

> **User (follow-up):** "tell me more about the first one"

1. Intent: `problem_detail` (high)
2. `resolve_problem_contextual_reference("the first one", session)`:
   - "first" + "one" → index 0 of `last_problem_list` → `"PB-MOCK-01"`
3. DB query: `Problem.id == "PB-MOCK-01"` + linked tickets
4. `build_problem_detail_payload()` → full detail card with linked ticket list

**No LLM was called for either message.**

---

### Story 4 — Agent asks for ticket recommendations

> **User:** "What are the AI recommendations for TW-MOCK-025?"

1. Intent: `recommendation_listing` (high) → `shortcut_recommendations`
2. Extract ticket ID: `"TW-MOCK-025"`
3. Load pre-computed `AIResolutionAdvice` for TW-MOCK-025 from DB
4. Format top 5 recommendations into response cards
5. Each card: action text, confidence bar, evidence source list

**No retrieval called at chat time** — the advice was pre-computed when the
ticket was created/updated.

---

### Story 5 — New agent joining the team creates a ticket

> **User:** "Create a ticket for a VPN login issue affecting the finance team"

1. `_is_explicit_ticket_create_request(...)` → `True`
2. `RoutingPlan(name="forced_create_ticket", use_llm=True, use_kb=True)`
3. LLM generates a `TicketDraft`:
   - `title`: "VPN login failure — finance team"
   - `category`: "network"
   - `priority`: "high" (finance = critical team)
   - `description`: draft text with affected users, symptoms
4. Classifier runs `classify_ticket()` for category/priority confirmation
5. `AISuggestionBundle` returned with draft + classification result

**User reviews and confirms. Ticket is created via `/api/tickets` endpoint.**

---

### Story 6 — AI summary on ticket detail page

**User opens ticket TW-MOCK-019 in the UI.**

1. `fetchTicketSummary("TW-MOCK-019")` called from `ticket-detail.tsx`
2. Backend: `ticket.summary_generated_at` is null → no cache
3. `unified_retrieve(db, query=ticket_text, top_k=5)`:
   - Returns 3 resolved similar tickets as RAG context
4. LLM prompt:
   ```
   Summarize this ITSM ticket in 2-3 sentences.
   Ticket: CRM sync job stalls after token rotation (priority: high)
   Description: ...
   Similar resolved tickets:
     - TW-MOCK-008: Resolved by rotating OAuth token and restarting sync job
     - TW-MOCK-012: Resolved by clearing stale token cache
   ```
5. LLM generates: *"High-priority CRM sync failure following token rotation.
   Root cause is likely a stale OAuth credential in the sync job cache.
   Suggested next step: rotate token, clear cache, restart sync job."*
6. Truncated at 500 chars, stored to `ticket.ai_summary`, timestamp set
7. Returned as `{ summary: "...", cached: false }`

**On next page open within 60 minutes:** returned immediately from DB cache.

---

## 7. Key Constants and Thresholds

All constants are in `backend/app/services/ai/calibration.py`.

| Constant | Value | Meaning |
|----------|-------|---------|
| `CONFIDENCE_HIGH_THRESHOLD` | 0.78 | `confidence_band = "high"` above this |
| `CONFIDENCE_MEDIUM_THRESHOLD` | 0.52 | `confidence_band = "medium"` above this |
| `GUIDANCE_CONFIDENCE_THRESHOLD` | 0.60 | Min confidence to return structured guidance |
| `CHAT_KB_SEMANTIC_MIN_SCORE` | 0.55 | Min semantic score for KB result to be used in chat |
| `DEFAULT_RESOLVER_TOP_K` | 5 | Max evidence items retrieved |
| `LLM_GENERAL_ADVISORY_CONFIDENCE` | 0.25 | Fixed confidence for LLM advisory cards |
| `LLM_GENERAL_ADVISORY_TIMEOUT_SECONDS` | 8 | Max seconds for LLM advisory call |
| `MAX_CHAT_RECOMMENDATIONS` | 5 | Max recommendations shown in chat |
| `NEGATION_WINDOW_SIZE` | 4 | Tokens checked for negation context |
| `SUMMARY_CACHE_TTL_MINUTES` | 60 | Minutes before summary is regenerated |
| `SUMMARY_MAX_SIMILAR_TICKETS` | 3 | RAG tickets used for summary generation |
| `SUMMARY_MAX_LENGTH_CHARS` | 500 | Max characters in a generated summary |

**Evidence cluster thresholds:**

| Constant | Value | Meaning |
|----------|-------|---------|
| `support_min_coherence` | 0.42 | Min coherence for an item to be a cluster support |
| `anchored_top_coherence` | 0.68 | Top-item coherence for an "anchored" cluster |
| `anchored_cluster_score` | 0.38 | Cluster score floor for "anchored" selection |
| `strong_top_coherence` | 0.82 | Top-item coherence for "strong" cluster |
| `strong_cluster_score` | 0.70 | Cluster score floor for "strong" selection |
| `conflict_margin` | 0.14 | If second cluster within this margin → conflict flagged |

---

## 8. File Map

```
backend/app/services/ai/
├── orchestrator.py          Chat entry point, routing, shortcut handlers
├── intents.py               Intent detection (rules + LLM fallback)
├── conversation_policy.py   Keyword lists and STATUS_KEYWORD_MAP
├── chat_session.py          Session state, contextual reference resolution
├── chat_payloads.py         Format helpers for structured chat cards
├── retrieval.py             unified_retrieve, coherence scoring, clustering
├── resolution_advisor.py    build_resolution_advice, LLM general advisory
├── resolver.py              resolve_ticket_advice, resolve_problem_advice
├── calibration.py           ALL numeric thresholds and constants
├── taxonomy.py              Topic, domain, signal vocabulary lists
├── topic_templates.py       Action/diagnostic text templates by topic
├── summarization.py         AI ticket summary with TTL cache + RAG
├── classifier.py            classify_ticket, priority/category inference
├── llm.py                   ollama_generate, extract_json
├── prompts.py               build_chat_prompt, build_chat_grounded_prompt
├── feedback.py              User vote aggregation for retrieval boosting
├── ai_sla_risk.py           SLA advisory (deterministic + hybrid)
├── analytics_queries.py     Data query handler (_answer_data_query)
├── formatters.py            Text formatters for shortcut responses
└── quickfix.py              Append known solutions to existing tickets

backend/app/services/
├── embeddings.py            compute_embedding, search_kb, search_kb_issues
├── jira_kb/
│   ├── snapshot.py          Build in-memory Jira KB snapshot
│   └── semantic.py          Semantic search over Jira KB
└── recommendations.py       /recommendations route service layer

frontend/components/
├── ticket-chatbot.tsx        Chat UI, message rendering, typing indicator
├── ticket-detail.tsx         Ticket detail + AI summary panel + SLA panel
├── recommendations.tsx       Recommendations page with ConfidenceBar
├── recommendation-sections.tsx  Evidence card sections
└── ui/
    ├── confidence-bar.tsx    4-band visual confidence indicator
    └── insight-popup.tsx     Desktop modal / mobile bottom-sheet

frontend/lib/
├── tickets-api.ts            fetchTicketSummary, fetchTicket, etc.
├── recommendations-api.ts    fetchRecommendations
└── badge-utils.ts            getBadgeStyle() for status/priority badges
```

---

*This document reflects the state of the codebase as of 2026-03-26.*
*For the most recent migration chain, see `backend/alembic/versions/` — currently ends at `0033_add_ticket_summary`.*
