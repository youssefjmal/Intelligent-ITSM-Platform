# ITSM AI Copilot Platform — Full Project Overview
> Read this file first. It gives a complete picture of the project without needing to parse individual source files.
> Last updated: 2026-04-04

---

## 1. What this project is

An **ITSM (IT Service Management) platform** built as a 5-month Cycle Ingénieur PFE at FST Monastir, developed during an internship at **Teamwill Consulting** (credit & asset finance consulting, 20 years, 100+ consultants, 25 countries).

The platform replaces manual Jira Service Management workflows with an AI copilot that:
- Classifies tickets automatically (priority, category, type) using LLM + semantic search
- Provides RAG-grounded resolution recommendations per ticket
- Detects recurring problem patterns and auto-creates Problem records
- Monitors SLA compliance and escalates at-risk tickets proactively
- Offers a chat assistant grounded in the resolved-ticket knowledge base
- Logs all AI decisions for governance and traceability (ISO 42001)

---

## 2. Tech stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, SQLAlchemy 2, Alembic, Python 3.13 |
| Database | PostgreSQL with pgvector extension |
| AI models | Ollama (local) — qwen3:4b (LLM), nomic-embed-text (embeddings) |
| Cache | Redis 7 via redis[hiredis] — two-level (L1=lru_cache, L2=Redis) |
| Frontend | Next.js 15 App Router, React, Tailwind CSS, shadcn/ui |
| Integration | Jira Service Management via REST API |
| Auth | JWT (access + refresh tokens), HttpOnly cookies |
| Migrations | Alembic — 34 migrations, chain ends at 0034_add_ai_classification_logs |

---

## 3. Directory structure

```
jira-ticket-managementv2/
├── backend/
│   ├── app/
│   │   ├── core/           config, deps, cache, rate_limit, security
│   │   ├── db/             session, base
│   │   ├── models/         SQLAlchemy ORM models
│   │   ├── schemas/        Pydantic request/response schemas
│   │   ├── routers/        FastAPI route handlers
│   │   ├── services/       Business logic layer
│   │   │   ├── ai/         AI pipeline (orchestrator, classifier, resolver, etc.)
│   │   │   ├── sla/        SLA monitor + auto-escalation
│   │   │   └── jira_kb/    Jira knowledge base snapshot + semantic indexing
│   │   └── integrations/
│   │       └── jira/       Jira sync, mapper, outbound, SLA sync
│   ├── alembic/versions/   34 migration files
│   └── requirements.txt
├── frontend/
│   ├── app/                Next.js App Router pages
│   │   ├── admin/          Admin, analytics, performance, ai-governance
│   │   ├── tickets/        Ticket list + detail
│   │   ├── problems/       Problem management
│   │   └── recommendations/ Recommendation page
│   ├── components/         React components
│   └── lib/                API clients, auth, i18n, utilities
├── docs/                   Architecture docs, diagrams, guides
└── rapport/pfe/            LaTeX PFE report
```

---

## 4. Key models (database tables)

| Model | Table | Purpose |
|---|---|---|
| Ticket | tickets | Core ticket with SLA, AI, Jira fields |
| TicketComment | ticket_comments | Comments with Jira sync |
| Problem | problems | Auto-detected recurring incident patterns |
| Recommendation | recommendations | AI-generated resolution recommendations |
| AiSolutionFeedback | ai_solution_feedback | User feedback on AI recommendations |
| AiClassificationLog | ai_classification_logs | Every AI classification decision (governance) |
| KbChunk | kb_chunks | pgvector chunks from Jira KB articles |
| Notification | notifications | User notifications |
| User | users | System users with RBAC roles |
| SLAPolicy | sla_policies | SLA configuration per priority |
| TicketHistoryEvent | ticket_history_events | Full audit trail of ticket changes |

---

## 5. User roles (RBAC)

| Role | Access |
|---|---|
| `admin` | Full access — user management, admin pages, all tickets |
| `agent` | Tickets assigned to them + AI features |
| `viewer` | Read-only on their own tickets |

---

## 6. API routers

| Router | Prefix | Key endpoints |
|---|---|---|
| tickets | /api/tickets | GET /, GET /stats, GET /insights, PATCH /{id}, PATCH /{id}/triage, POST /classify-draft, GET /{id}/similar |
| ai | /api/ai | POST /chat, POST /classify, POST /suggest, POST /feedback, GET /classification-logs |
| recommendations | /api/recommendations | GET /, GET /sla-strategies, POST /{id}/feedback |
| problems | /api/problems | GET /, POST /, GET /{id}, PATCH /{id} |
| sla | /api/sla | GET /dashboard, GET /at-risk, GET /breached |
| integrations_jira | /api/integrations/jira | POST /sync, GET /status |
| search | /api/search | GET /?q= |
| users | /api/users | CRUD for user management (admin only) |
| auth | /api/auth | login, logout, refresh, register |
| notifications | /api/notifications | GET /, PATCH /{id}/read |

---

## 7. AI pipeline — the core of the platform

### 7.1 Classification pipeline
Entry: `POST /api/ai/classify` or automatic on Jira sync
File: `backend/app/services/ai/classifier.py`

```
title + description
    ↓
_load_strong_similarity_matches()   ← pgvector cosine search in kb_chunks
    ↓
if strong matches (score ≥ 0.72):
    infer priority/category/type from matches
    skip LLM → decision_source = "semantic"
else:
    build_classification_prompt() → ollama_generate() → extract_json()
    decision_source = "llm"
if LLM fails:
    _rule_based_classify()   ← keyword matching
    decision_source = "fallback"
    ↓
apply_category_guardrail()   ← prevents nonsensical category overrides
    ↓
_log_classification()   → ai_classification_logs table
    ↓
return { priority, category, ticket_type, confidence, recommendations }
```

Key constants:
- `DUPLICATE_SIMILARITY_THRESHOLD = 0.72`
- `AI_CLASSIFY_MAX_RECOMMENDATIONS` from settings
- Confidence band thresholds in `calibration.py`

### 7.2 Chat pipeline
Entry: `POST /api/ai/chat`
File: `backend/app/services/ai/orchestrator.py → handle_chat()`

```
ChatRequest (messages[], locale)
    ↓
classify_intent()   ← intents.py, regex + keyword matching
    ↓
[intent routing]
├── ticket_search    → search tickets, return TicketResults payload
├── ticket_detail    → load ticket, return detail payload
├── problem_listing  → list problems
├── problem_detail   → load problem detail
├── create_ticket    → extract fields, return AISuggestedTicket
├── update_ticket    → extract changes, apply via service
├── sla_query        → SLA dashboard data
├── recommendation_listing → list recommendations
└── general_question ↓
        resolve_chat_guidance()   ← resolver.py
            ↓
        unified_retrieve()   ← pgvector search in kb_chunks + resolved tickets
            ↓
        build_resolution_advice()   ← resolution_advisor.py
            5 display modes:
            - evidence_action       (resolved similar ticket found)
            - tentative_diagnostic  (partial match, moderate confidence)
            - service_request       (service request guidance)
            - llm_general_knowledge (no KB match, pure LLM)
            - no_strong_match       (low confidence, triage advised)
            ↓
        build_chat_reply()   ← formatters.py
            ↓
        ChatResponse (reply, response_payload, rag_grounding, suggestions)
```

Key constants:
- `NEGATION_WINDOW_SIZE = 4` — negation detection in resolver
- `LLM_GENERAL_ADVISORY_CONFIDENCE = 0.25`
- `LLM_FALLBACK_DEFAULT_CONFIDENCE = "low"`
- `_matches_keyword()` uses `\b` regex for single words, substring for phrases

### 7.3 Recommendation pipeline
Entry: `GET /api/recommendations/`
File: `backend/app/services/recommendations.py → list_recommendations()`

```
list all visible tickets for user
    ↓
filter: critical + active tickets (max 3) + service request tickets
    ↓
for each candidate ticket:
    classify_ticket_detailed()   ← use_llm=False (semantic only, fast)
    validate_ticket_routing()    ← incident vs service_request routing check
    ↓
    if service_request:
        build_service_request_guidance()
    else:
        resolve_ticket_advice()   ← full RAG pipeline
            ↓
            unified_retrieve() → build_resolution_advice()
    ↓
    build RecommendationView
    ↓
attach active problems (max 2)
    ↓
deduplicate + limit to 18 items
    ↓
Redis cache (15 min TTL, keyed by user_id + locale)
```

### 7.4 Embedding pipeline
File: `backend/app/services/embeddings.py`

```
compute_embedding(text)
    ↓
L2 cache check: Redis key = "itsm:embedding:{sha256(normalized_text)}"
    ↓ (miss)
_do_compute_embedding(normalized)
    ↓
POST /api/embeddings to Ollama (nomic-embed-text, 768 dims)
GPU retry logic: try num_gpu=1, fallback num_gpu=0
    ↓
store in Redis (TTL = 86400s = 24h)
    ↓
return list[float] (768 dimensions)

L1 cache = @lru_cache on callers (retrieval.py, problems.py)
```

### 7.5 Problem auto-detection
File: `backend/app/services/problems.py → link_ticket_to_problem()`

Called automatically on every ticket update/sync.

```
ticket saved to DB
    ↓
compute_similarity_key(title, category, description, tags)
    ↓
_find_similar_problem()   ← check existing problems for match
    ↓ (no match)
_recent_similar_tickets()   ← find tickets with hybrid similarity ≥ 0.45
    hybrid = jaccard(tokens) + cosine(embeddings)
    ↓
if count < 5: return None   (PROBLEM_TRIGGER_MIN_COUNT = 5)
    ↓
get_or_create_problem()   ← auto-creates Problem record
link all candidates to problem
recompute_problem_stats()
```

Key constants:
- `PROBLEM_TRIGGER_MIN_COUNT = 5`
- `PROBLEM_MATCH_SCORE_THRESHOLD = 0.45`

---

## 8. Caching layer

File: `backend/app/core/cache.py`

Key format: `itsm:{resource}:{user_id}[:{params_hash12}]`

| Cache key | TTL | Endpoint |
|---|---|---|
| itsm:stats:{uid} | 300s | GET /tickets/stats |
| itsm:insights:{uid} | 300s | GET /tickets/insights |
| itsm:performance:{uid}:{hash} | 900s | GET /tickets/performance |
| itsm:agent_perf:{uid}:{hash} | 1200s | GET /tickets/agent-performance |
| itsm:similar:{uid}:{hash} | 600s | GET /tickets/{id}/similar |
| itsm:recommendations:{uid}:{hash} | 900s | GET /recommendations/ |
| itsm:sla_strategies:{uid}:{hash} | 1200s | GET /recommendations/sla-strategies |
| itsm:embedding:{sha256} | 86400s | compute_embedding() |

Invalidation:
- `_bust_ticket_analytics(user_id)` called on every PATCH /tickets/{id}
- Recommendation keys cleared on POST /recommendations/{id}/feedback
- Graceful fallback: if Redis is down, all cache functions return None/False silently

---

## 9. Jira integration

Files: `backend/app/integrations/jira/`

| File | Purpose |
|---|---|
| client.py | HTTP client wrapping Jira REST API |
| mapper.py | Maps Jira issue JSON → NormalizedTicket (4-layer category detection) |
| service.py | Upsert logic — create/update tickets from Jira data, AI classification, problem linking |
| auto_reconcile.py | Background task — runs sync every 5 minutes |
| outbound.py | Write back to Jira (status changes, comments, assignments) |
| sla_sync.py | Parse Jira SLA payload, store locally |

Sync flow:
1. `auto_reconcile` calls `sync_all_issues()` every 300s
2. Each issue goes through `_upsert_issue_bundle()`
3. Mapper extracts: title, description, priority, category (4-layer rule-based), type
4. If any field was "defaulted" → AI classifier runs and overrides
5. `link_ticket_to_problem()` called on every ticket
6. SLA payload parsed and stored

---

## 10. SLA system

Files: `backend/app/services/sla/`

- `sla_monitor.py` — background task (every 300s), scans for tickets at ≥75% SLA consumed (`PROACTIVE_SLA_AT_RISK_RATIO_THRESHOLD = 0.75`), sends notifications, deduplicates alerts per 60 min
- `auto_escalation.py` — escalates priority when SLA is about to breach
- `backend/app/integrations/jira/sla_sync.py` — parses Jira SLA payload into local fields

SLA fields on Ticket model:
- `sla_status`: ok | at_risk | breached | paused | completed | unknown
- `sla_first_response_due_at`, `sla_resolution_due_at`
- `sla_remaining_minutes`, `sla_elapsed_minutes`
- `sla_first_response_breached`, `sla_resolution_breached`

---

## 11. Frontend pages

| Route | Component | Purpose |
|---|---|---|
| / | Dashboard | Stats, recent tickets, SLA overview |
| /tickets | TicketList | Filterable ticket table |
| /tickets/[id] | TicketDetail | Full ticket view with AI recommendations + chatbot |
| /recommendations | Recommendations | AI recommendations page (cached 15min) |
| /problems | ProblemList | Auto-detected problems |
| /problems/[id] | ProblemDetail | Problem detail with linked tickets |
| /admin | AdminPage | User management |
| /admin/analytics | AnalyticsPage | AI recommendation feedback analytics |
| /admin/performance | PerformancePage | Agent performance metrics |
| /admin/ai-governance | AIGovernancePage | AI classification audit log |

Key components:
- `ticket-chatbot.tsx` — full chat UI with RAG grounding indicator, AbortController on navigation, grouped shortcut grid, persistent shortcut strip (15 shortcuts), redesigned bubbles and header
- `ticket-detail.tsx` — ticket detail with triage panel, AI suggestion card, similar tickets, `no_strong_match` fallback action display
- `app-sidebar.tsx` — nav sidebar with RBAC-aware links
- `recommendation-sections.tsx` — all AI recommendation display blocks (evidence, reasoning, root cause, LLM advisory, feedback)
- `confidence-bar.tsx`, `insight-popup.tsx` — shared AI confidence UI

---

## 12. Recent features (batch 2026-04-02 to 2026-04-04)

- **Redis caching** — 7 endpoints cached + embedding L2 cache (see section 8)
- **AI Classification Audit Log** — `ai_classification_logs` table (migration 0034), `GET /api/ai/classification-logs`, `/admin/ai-governance` frontend page with filters, badges, pagination
- **Chatbot crash protection** — try/except in orchestrator + router-level fallback in `ai.py`
- **AbortController** — in-flight chat requests cancelled on navigation; prevents RAG from blocking the UI
- **Thread pool** — bumped to 60 threads in `main.py` lifespan to prevent LLM calls from starving other endpoints
- **Problem auto-detection** — confirmed `PROBLEM_TRIGGER_MIN_COUNT=5` triggers Problem record creation automatically on ticket sync
- **SLA CSV export** — `GET /api/sla/export` returns a downloadable `.csv` with 14 SLA columns for all tickets
- **`no_strong_match` display fix** — when LLM produced a `fallback_action`, it is now shown in the recommendation card instead of showing nothing
- **LLM intent classifier upgrade** — prompt rewritten with all 11 `ChatIntent` labels + 25 few-shot examples in FR/EN; previously used only 4 coarse labels
- **Intent keyword expansion** — `high priority`, `network tickets`, `email tickets`, `sla at risk`, `known errors` etc. added to `conversation_policy.py` for rule-based detection before LLM fallback
- **Chat shortcuts** — 5 grouped shortcut categories in empty state (Tickets, Categories, SLA & Risk, Problems & AI, Analytics); 15-shortcut persistent horizontal strip shown during conversation
- **Chatbot UI overhaul** — redesigned header with green status dot, message count, grouped shortcuts grid, improved bubble shapes (rounded corners asymmetric), spinner on send button, clear (×) input button

---

## 13. Known limitations / future work

- **Mock data** — real Jira credentials/production data not yet received. RAG quality is limited until real resolved tickets populate the KB.
- **LLM swap pending** — currently `qwen3:4b` via Ollama. Will be replaced with a more capable hosted model once access is granted. Swap point: `OLLAMA_MODEL` in config + `llm.py`.
- **Embedding model swap pending** — currently `nomic-embed-text` (768 dims). May require recomputing all kb_chunks embeddings after swap.
- **SMTP → Microsoft Teams OAuth** — SMTP notifications will be replaced with Teams webhook/Graph API (OAuth). Reason: SMTP security concerns (no MFA, credentials in env). Teamwill already uses Teams.
- **Grafana + Prometheus** — not yet implemented. Planned as last feature before defence. Will expose `/metrics` endpoint with request latency, AI pipeline duration, cache hit rates, SLA breach counts.
- **ISO 42001 + ISO 27001 compliance** — targeted. ISO 42001 (AI governance) is partially covered by `ai_classification_logs`. ISO 27001 requires full audit trail and access control review.
- No conversation history persistence (future work — mentioned in rapport as perspectives)
- AI classifier skips category override for most Jira tickets — category is always rule-based via mapper

---

## 14. Environment variables (key ones)

```env
DATABASE_URL=postgresql+psycopg://...
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:4b
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_EMBEDDING_DIM=768
REDIS_URL=redis://localhost:6379/0
CACHE_ENABLED=true
JIRA_BASE_URL=https://your-org.atlassian.net
JIRA_EMAIL=...
JIRA_API_TOKEN=...
JIRA_PROJECT_KEY=...
SECRET_KEY=...
```

---

## 15. Running the project

```bash
# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev

# Redis (Docker)
docker run -d -p 6379:6379 --name redis redis:7-alpine

# Ollama
ollama pull qwen3:4b
ollama pull nomic-embed-text
```
