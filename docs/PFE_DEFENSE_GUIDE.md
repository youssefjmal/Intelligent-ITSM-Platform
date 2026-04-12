# PFE Defense Guide — ITSM AI Platform
## Complete Technical Understanding for Oral Defense

> **Purpose**: This guide is written for someone who built this project with AI assistance
> and now needs to fully understand every layer to answer jury questions confidently.
> Read it section by section. Each section ends with the questions you will likely be asked.

---

## TABLE OF CONTENTS

1. [The Big Picture — What You Built](#1-the-big-picture)
2. [Why These Technologies](#2-why-these-technologies)
3. [How the Backend Works (FastAPI)](#3-how-the-backend-works)
4. [How the Database Works (PostgreSQL + pgvector)](#4-how-the-database-works)
5. [How the Frontend Works (Next.js)](#5-how-the-frontend-works)
6. [The AI Pipeline — Full Walkthrough](#6-the-ai-pipeline)
7. [Authentication & Security](#7-authentication--security)
8. [Jira Integration](#8-jira-integration)
9. [n8n Orchestration](#9-n8n-orchestration)
10. [SLA Management](#10-sla-management)
11. [ITIL Concepts in the Platform](#11-itil-concepts)
12. [ISO 27001 & ISO 42001](#12-iso-standards)
13. [The Full Request Lifecycle — Tracing One Action End-to-End](#13-full-request-lifecycle)
14. [Common Defense Questions & Answers](#14-defense-questions)

---

## 1. THE BIG PICTURE

### What you built in one sentence
A web platform that sits on top of Jira Service Management, adds an AI brain to it, and gives IT support teams smarter tools to handle tickets faster.

### The three layers

```
┌─────────────────────────────────────────┐
│  FRONTEND  (Next.js — what users see)   │
│  - Ticket list, dashboard, chatbot UI   │
└──────────────────┬──────────────────────┘
                   │ HTTP requests (JSON)
┌──────────────────▼──────────────────────┐
│  BACKEND  (FastAPI — the brain)         │
│  - Handles all business logic           │
│  - Runs the AI pipeline                 │
│  - Talks to the database                │
└──────────────────┬──────────────────────┘
                   │ SQL queries
┌──────────────────▼──────────────────────┐
│  DATABASE  (PostgreSQL + pgvector)      │
│  - Stores tickets, users, AI logs       │
│  - Stores vector embeddings for search  │
└─────────────────────────────────────────┘
         │                    │
         ▼                    ▼
   Jira Service          Ollama (LLM)
   Management            running locally
```

### Why is it "intelligent"?
The platform uses three AI techniques:
1. **Classification** — reads a ticket title+description and automatically assigns category, priority, ticket type
2. **Semantic search** — converts text into numbers (vectors) and finds similar tickets by meaning, not keywords
3. **Chat assistant** — understands natural language questions about tickets and generates grounded answers

---

## 2. WHY THESE TECHNOLOGIES

### FastAPI (Python backend)
**What it is**: A modern Python framework for building web APIs (Application Programming Interface — a system that receives requests and sends back responses).

**Why you chose it**:
- Python is the natural language for AI/ML work. All the best AI libraries (transformers, numpy, langchain concepts) are Python-first.
- FastAPI is extremely fast for Python (uses async I/O) and generates automatic API documentation at `/docs`.
- Type safety via Pydantic — every input and output is validated automatically, which reduces bugs.

**Alternative you could have used**: Django REST Framework, Flask. FastAPI is faster and more modern.

### Next.js (React frontend)
**What it is**: A framework for building web interfaces. React is the core library (components, state); Next.js adds routing, server-side rendering, and file-based pages on top.

**Why you chose it**:
- App Router (Next.js 13+) gives each folder under `app/` its own URL automatically.
- Server-side and client-side rendering options depending on the page.
- Tailwind CSS (utility classes) makes styling fast without writing custom CSS files.

**Alternative**: Plain React + React Router, Vue.js, Angular. Next.js is the industry standard for production React apps.

### PostgreSQL + pgvector
**What it is**: PostgreSQL is a relational database (tables, rows, SQL). pgvector is an extension that adds a new column type called `vector` and lets you do mathematical similarity searches.

**Why you chose it**:
- Tickets, users, SLA data = structured relational data → perfect for SQL tables.
- AI embeddings (the numeric representation of text) = arrays of 768 numbers → stored in pgvector columns.
- Having both in the same database avoids running a separate vector database (Pinecone, Weaviate, etc.).

### Ollama (local LLM)
**What it is**: A tool that runs large language models locally on your machine, no API key or internet needed.

**Why you chose it**: The project is designed for an enterprise DSI (IT department). Sending internal ticket data to OpenAI's cloud would be a data privacy issue. Running locally keeps everything on-premise.

**Model used**: `qwen3:4b` for generation, `nomic-embed-text` for embeddings.

### Redis (caching)
**What it is**: An in-memory key-value store. Think of it as a very fast temporary notepad.

**Why you chose it**: The AI pipeline is slow (LLM calls take 2-10 seconds). For data that doesn't change often (ticket statistics, SLA strategies), you cache the result in Redis and serve it instantly for the next 5-20 minutes instead of recomputing.

### Alembic (database migrations)
**What it is**: A tool that tracks changes to your database schema (table structures) over time, like git for your database.

**Why it matters**: When you add a new column (e.g., `failed_login_attempts` on the `users` table), you write an Alembic migration file. Running `alembic upgrade head` applies all pending changes to the live database without losing existing data.

### n8n (workflow automation)
**What it is**: A low-code automation tool (similar to Zapier or Make). You build workflows visually by connecting nodes.

**Why you chose it**: The PFE spec required workflow orchestration. n8n sits between your backend and external systems (email, Teams) and triggers workflows on events (SLA breach → send alert).

---

## 3. HOW THE BACKEND WORKS

### The request-response cycle
Every time the frontend does something (load tickets, send a chat message), it sends an HTTP request to the backend. Here is what happens:

```
Browser sends: POST /api/auth/email-login  { email, password }
     │
     ▼
1. CORS middleware — checks the request comes from an allowed origin (localhost:3000)
2. Rate limit middleware — checks the IP hasn't sent too many requests
3. Security headers middleware — adds X-Frame-Options, CSP to the response
4. Router (auth.py) — finds the matching function: email_login()
5. Dependency injection — FastAPI creates a DB session, injects it
6. Service layer (services/auth.py) — authenticate_user() checks password
7. Response — returns UserOut JSON with cookies set
```

### File structure — backend

```
backend/app/
├── main.py              ← Entry point. Creates the FastAPI app, registers routers, starts background tasks
├── core/
│   ├── config.py        ← All settings loaded from .env (DATABASE_URL, JWT_SECRET, etc.)
│   ├── deps.py          ← Reusable dependencies: get_current_user, require_admin
│   ├── security.py      ← JWT creation/verification, bcrypt password hashing
│   ├── rate_limit.py    ← Redis sliding-window rate limiter
│   ├── cache.py         ← Redis cache wrapper (get/set/delete with TTL)
│   └── exceptions.py    ← Custom exception classes (AuthenticationException, NotFoundError...)
├── db/
│   ├── base.py          ← SQLAlchemy declarative base (all models inherit from this)
│   └── session.py       ← Creates DB engine and session factory; get_db() dependency
├── models/              ← SQLAlchemy ORM models (one file per database table)
│   ├── ticket.py        ← Ticket table
│   ├── user.py          ← User table (with failed_login_attempts, locked_until)
│   ├── security_event.py← security_events audit table
│   └── ai_classification_log.py ← AI decision audit table
├── schemas/             ← Pydantic schemas (what the API accepts/returns)
│   ├── ticket.py        ← TicketCreate, TicketOut, TicketUpdate
│   └── user.py          ← UserCreate, UserOut, UserLogin
├── routers/             ← One file per resource group (URL prefix)
│   ├── auth.py          ← /api/auth/*
│   ├── tickets.py       ← /api/tickets/*
│   ├── ai.py            ← /api/ai/*
│   ├── sla.py           ← /api/sla/*
│   └── security.py      ← /api/admin/security-events, /api/admin/compliance-summary
└── services/            ← Business logic (no HTTP, no DB session management)
    ├── auth.py          ← authenticate_user, issue_auth_tokens, unlock_user
    ├── tickets.py       ← create_ticket, update_ticket, get_ticket
    └── ai/              ← The entire AI pipeline (see Section 6)
```

### What is a "model" vs a "schema"?

| | Model (SQLAlchemy) | Schema (Pydantic) |
|---|---|---|
| Purpose | Represents a database table | Represents data coming in/going out of the API |
| Location | `app/models/` | `app/schemas/` |
| Example | `User` class with columns `id`, `email`, `password_hash` | `UserOut` class with fields `id`, `email`, `name` (no password) |
| Usage | Used in service layer to query the DB | Used in router to validate input and serialize output |

**Key insight**: The schema is what you expose to the outside world. The model is how data is stored internally. You never send `password_hash` to the browser — the `UserOut` schema simply doesn't include that field.

### What is dependency injection?

In `tickets.py` router:
```python
@router.get("/{ticket_id}")
def get_ticket(ticket_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
```

`Depends(get_db)` means "before calling this function, call `get_db()` and give me the result as `db`". FastAPI handles this automatically. You never manually create a database session or decode a JWT token in a router — you just declare what you need and it's injected.

### What is a migration (Alembic)?

Every file in `backend/alembic/versions/` is a migration. Each has:
- `revision` — its unique ID (e.g., `0035_security_hardening`)
- `down_revision` — the previous migration (forms a chain)
- `upgrade()` — what to do when applying (add column, create table)
- `downgrade()` — how to undo it

Running `alembic upgrade head` walks the chain from your current version to the latest and applies each `upgrade()` in order.

---

## 4. HOW THE DATABASE WORKS

### Why PostgreSQL + pgvector together?

The platform needs two fundamentally different types of data storage:

1. **Structured data** (tickets, users, SLA records) — stored in normal SQL tables with columns and foreign keys. You query them with `WHERE status = 'open'` or `JOIN`.

2. **Vector data** (AI embeddings) — stored as arrays of 768 floating-point numbers. You query them with cosine similarity: "find the 5 vectors closest to this one". pgvector adds this capability directly to PostgreSQL.

### Key tables and what they store

| Table | Purpose |
|-------|---------|
| `users` | Accounts: email, hashed password, role, lockout fields |
| `tickets` | Core ITSM objects: title, description, status, priority, SLA fields |
| `refresh_tokens` | Active session tokens (for logout/revocation) |
| `ai_solution_feedback` | User thumbs up/down on AI recommendations |
| `ai_classification_logs` | Audit trail of every AI classification decision |
| `security_events` | Audit trail of all security-relevant actions |
| `kb_chunks` | Knowledge base chunks from Jira, with `embedding vector(768)` column |
| `notifications` | Per-user notification records |
| `problems` | ITIL Problem records linked to recurring incident patterns |

### What is an embedding?

When the AI needs to find tickets similar to "my printer is not working", it cannot compare text strings directly. Instead:

1. The text is fed to `nomic-embed-text` (an embedding model)
2. The model outputs a vector: `[0.12, -0.45, 0.87, ... 768 numbers total]`
3. This vector captures the **meaning** of the sentence mathematically
4. "my printer is broken" would produce a very similar vector
5. "please reset my password" would produce a very different vector

pgvector stores these vectors and the query `ORDER BY embedding <=> query_vector LIMIT 5` returns the 5 most semantically similar tickets.

### The `<=>` operator

This is pgvector's cosine distance operator. Cosine similarity measures the angle between two vectors:
- Distance = 0 means identical meaning
- Distance = 1 means completely unrelated
- The query returns the smallest distances (most similar)

### Foreign keys and relationships

```
users ──< tickets (assignee)
users ──< ai_solution_feedback
users ──< security_events (user_id + actor_id)
tickets ──< ai_classification_logs (ticket_id)
tickets ──< ai_solution_feedback (ticket_id)
```

`──<` means "one to many". One user can have many tickets. One ticket can have many feedback records.

---

## 5. HOW THE FRONTEND WORKS

### Next.js App Router — the file = URL rule

Every `page.tsx` file inside `frontend/app/` becomes a URL:

```
frontend/app/
├── page.tsx                    →  /
├── tickets/
│   └── page.tsx                →  /tickets
├── admin/
│   ├── page.tsx                →  /admin
│   ├── ai-governance/
│   │   └── page.tsx            →  /admin/ai-governance
│   └── security/
│       └── page.tsx            →  /admin/security
└── auth/
    └── login/
        └── page.tsx            →  /auth/login
```

No routing configuration needed. The folder structure IS the routes.

### "use client" — what does it mean?

Next.js can render pages on the server (faster first load, better SEO) or on the client (interactive, can use browser APIs). The `"use client"` directive at the top of a file means "this component runs in the browser". Without it, the component would run on the server and couldn't use `useState`, `useEffect`, or event handlers.

**Rule of thumb**: Any page that fetches data after load, or responds to user interactions, needs `"use client"`.

### React components — the building blocks

A component is a JavaScript function that returns HTML-like code (called JSX):

```tsx
function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border p-4">
      <p className="text-sm">{label}</p>
      <p className="text-2xl font-bold">{value}</p>
    </div>
  )
}
```

The `className` attribute uses Tailwind CSS utility classes instead of writing CSS. `rounded` means `border-radius: 4px`, `p-4` means `padding: 1rem`, `text-2xl` means `font-size: 1.5rem`.

### useState and useEffect — React's two most important hooks

**useState** — stores a value that, when changed, re-renders the component:
```tsx
const [tickets, setTickets] = useState<Ticket[]>([])
// tickets = current value
// setTickets = function to update it (triggers re-render)
```

**useEffect** — runs code after the component renders (used for fetching data):
```tsx
useEffect(() => {
  fetchTickets()   // called once when component mounts
}, [])             // empty array = run once only
```

### How data flows from backend to frontend

```
1. Component mounts → useEffect fires
2. apiFetch("/tickets") called  (frontend/lib/api.ts)
3. fetch("http://localhost:8000/api/tickets") sent
4. Backend router returns JSON array
5. setTickets(data) called
6. React re-renders the component with the new data
7. Table rows appear on screen
```

### The auth context (frontend/lib/auth.tsx)

Instead of every page fetching the current user separately, a React Context wraps the whole app. The `AuthProvider` component:
- Fetches the current user on app load via `/api/auth/me`
- Stores the user in state
- Exposes `user`, `signIn()`, `signOut()`, `hasPermission()` to any component via `useAuth()`

This is called the **Context API pattern** — global state without a library like Redux.

### AppShell — the persistent layout

`frontend/components/app-shell.tsx` wraps every authenticated page. It renders:
- The sidebar (navigation links)
- The top header (search, theme toggle, notifications, user menu)
- A `<main>` slot where the page content goes (`{children}`)

Every page is wrapped:
```tsx
export default function TicketsPage() {
  return (
    <AppShell>
      {/* page content here */}
    </AppShell>
  )
}
```

---

## 6. THE AI PIPELINE

This is the most important section. Understand this thoroughly.

### Overview — what happens when you ask the chatbot a question

```
User types: "What caused the recurring printer issues?"
     │
     ▼
frontend/components/ticket-chatbot.tsx
     │  POST /api/ai/chat  { message, ticket_id, history }
     ▼
backend/app/routers/ai.py  →  handle_chat()
     │
     ▼
backend/app/services/ai/orchestrator.py
  1. Detect intent (what does the user want?)
  2. Apply conversation policy (is this a follow-up?)
  3. Route to the right handler
  4. Retrieve relevant context (RAG)
  5. Call the LLM
  6. Format and return the response
     │
     ▼
frontend renders the AI response in the chat bubble
```

### Step 1 — Intent Detection (intents.py)

The orchestrator first classifies **what the user wants**. There are 11 intents:

| Intent | Triggered by | Example |
|--------|-------------|---------|
| `RECOMMENDATION_LISTING` | "give me solutions", "how to fix" | "How do I fix this error?" |
| `CAUSE_ANALYSIS` | "why", "cause", "reason" | "Why did this ticket get escalated?" |
| `TICKET_SUMMARY` | "summarize", "what happened" | "Summarize this ticket" |
| `PROBLEM_LISTING` | "problems", "recurring" | "What problems are active?" |
| `PROBLEM_DETAIL` | "tell me about problem" | "Tell me about the printer problem" |
| `SLA_STATUS` | "SLA", "deadline", "breach" | "Is this ticket at risk?" |
| `AGENT_PERFORMANCE` | "performance", "agents" | "Who resolves tickets fastest?" |
| `NETWORK_TICKETS` | "network", "réseau" | "Show network tickets" |
| `GENERAL_QUERY` | anything else | "Hello" |

Detection uses two methods:
1. **Keyword matching** with word-boundary regex (`\bwhy\b` matches "why" but not "whereby")
2. **LLM classification** — if keywords don't clearly match, the LLM is asked to classify with 25 few-shot examples

### Step 2 — RAG (Retrieval-Augmented Generation)

RAG is the core technique that makes the AI trustworthy. Instead of asking the LLM to answer from its training knowledge (which may be wrong or outdated), you:

1. **Retrieve** relevant documents from your database
2. **Augment** the LLM prompt with those documents
3. **Generate** an answer grounded in real data

```
User: "What caused ticket #42?"
         │
         ▼
Convert question to embedding vector
         │
         ▼
Search kb_chunks and similar tickets
(find the 5 most semantically similar)
         │
         ▼
Build prompt:
  "You are an ITSM assistant.
   Here is the ticket: [ticket data]
   Here are similar resolved tickets: [top 5 matches]
   Question: What caused ticket #42?
   Answer based ONLY on the above context."
         │
         ▼
LLM generates answer grounded in real ticket data
```

**Why RAG instead of just asking the LLM directly?**
Without RAG, the LLM would hallucinate (invent plausible-sounding but false answers). With RAG, it can only answer based on your actual tickets and knowledge base.

### Step 3 — The Resolution Advisor (resolution_advisor.py)

When the intent is `RECOMMENDATION_LISTING`, a 4-level trust hierarchy is applied:

```
Level 1: evidence_action
  → Strong semantic match found in KB (score ≥ 0.72)
  → High confidence. Shows an "Apply" button.

Level 2: tentative_diagnostic
  → Moderate match found (score 0.5–0.72)
  → Medium confidence. Shows as suggestion.

Level 3: llm_general_knowledge
  → No strong match. LLM answers from its general knowledge.
  → Low confidence (0.25 fixed). No "Apply" button.

Level 4: no_strong_match
  → LLM couldn't generate useful content either.
  → Shows a "manual triage needed" message.
```

This prevents the AI from presenting hallucinated answers with false confidence.

### Step 4 — The Chat Session (chat_session.py)

The chatbot maintains conversation memory within a session. The `ChatSession` object tracks:
- `last_intent` — what the previous question was about
- `last_problem_id` — if the user was discussing a specific problem
- `last_problem_list` — list of problems mentioned, so follow-ups like "tell me more about the second one" work

### The LLM wrapper (llm.py)

All LLM calls go through `llm.py`. This file:
1. Sends the prompt to Ollama via HTTP
2. Parses the JSON response from the model
3. Handles retries if the model returns malformed JSON
4. Strips markdown fences from the output

By centralizing all LLM calls here, swapping the model (Ollama → OpenAI → Anthropic) requires changing only this one file.

### The Embedding Service (embeddings.py)

All embedding calls go through `embeddings.py`. It has a **two-level cache**:
- **L1**: `@lru_cache` in Python memory — instant, per-process
- **L2**: Redis, keyed by SHA256 hash of the text, TTL 24 hours

Computing embeddings is slow (100-500ms each). Caching means the same text is embedded only once per day.

---

## 7. AUTHENTICATION & SECURITY

### The JWT flow

JWT (JSON Web Token) is a self-contained token that proves who you are. The flow:

```
1. User logs in with email + password
2. Backend verifies password with bcrypt
3. Backend creates a JWT: { "sub": "user-uuid", "role": "admin", "exp": ... }
   signed with a secret key
4. JWT sent as an HttpOnly cookie (browser cannot read it with JavaScript)
5. Every subsequent request automatically includes the cookie
6. Backend decodes the JWT, extracts user_id, loads user from DB
```

**Why HttpOnly cookie instead of localStorage?**
- `localStorage` can be stolen by XSS (JavaScript injection attacks)
- HttpOnly cookies are invisible to JavaScript — only the browser sends them automatically with requests
- This is the most secure way to store session tokens in a web app

### The two-token system

- **Access token**: Short-lived (1 hour). Used for every API call.
- **Refresh token**: Long-lived (14 days). Used only to get a new access token when the access token expires.

If the access token is stolen, it expires in 1 hour. The attacker cannot get a new one without the refresh token. This limits the damage window.

### Brute-force protection

The `users` table has `failed_login_attempts` (counter) and `locked_until` (timestamp).

Flow:
1. Wrong password → `failed_login_attempts += 1`
2. If `failed_login_attempts >= 5` → set `locked_until = now + 15 minutes`
3. While `locked_until > now` → return HTTP 423 with "account_locked_15min"
4. When `locked_until` expires → clear it automatically on next login attempt

### Rate limiting

The `rate_limit.py` module uses a **sliding window** algorithm:
- Keeps a sorted set in Redis with timestamps of recent requests
- On each request: remove old timestamps (outside the 60s window), count remaining, add current timestamp
- If count ≥ limit → return HTTP 429 Too Many Requests

**Why Redis?** If you run 4 Uvicorn worker processes, an in-memory limiter would have 4 independent counters. An attacker could bypass it by distributing requests across workers. Redis is shared across all workers.

### SameSite=Strict cookies

The `SameSite=Strict` attribute means the browser will never send the cookie on a cross-site request. This completely eliminates CSRF (Cross-Site Request Forgery) attacks — an attacker cannot trick the user's browser into sending authenticated requests to your API from another website.

---

## 8. JIRA INTEGRATION

### Bidirectional sync

The integration works in both directions:

**Inbound (Jira → Platform)**:
- Jira sends webhook events when tickets change (`jira_issue_created`, `jira_issue_updated`)
- The platform receives these at `POST /api/jira/webhook`
- The `mapper.py` translates Jira's field names to the platform's schema
- The ticket is created or updated in the local database

**Outbound (Platform → Jira)**:
- When an agent updates a ticket (status change, comment, assignment) in the platform
- `outbound.py` pushes the change to Jira via the REST API
- This keeps both systems synchronized

**Auto-reconcile**: A background task runs every 300 seconds. It fetches the last 30 days of Jira tickets and updates any that drifted out of sync (e.g., tickets changed directly in Jira without triggering a webhook).

### The Knowledge Base (jira_kb/)

Jira tickets that are resolved become "knowledge base articles". The process:
1. Fetch resolved issues from Jira API (up to 60 issues, 5 comments each)
2. Split each into chunks (title, description, resolution, comments separately)
3. Embed each chunk with `nomic-embed-text`
4. Store in `kb_chunks` table with the vector

This is what the RAG system searches when generating recommendations.

---

## 9. N8N ORCHESTRATION

### What n8n does in the platform

n8n is the "trigger + action" layer. The backend detects events and calls n8n webhooks; n8n handles the delivery.

```
Backend detects: SLA about to breach (75% consumed)
     │
     ▼
POST to n8n webhook URL
     │
     ▼
n8n workflow:
  → Format email / Teams message
  → Send to the right recipients
  → Log the notification
```

### The three production workflows

1. **SLA Breach Alerting**: Triggered by the proactive SLA monitor (`sla_monitor.py`) when a ticket consumes 75% of its SLA time. Sends an alert to the assignee and their manager.

2. **Critical Ticket Detector**: Triggered when a P1/Critical ticket is created. Immediately notifies the on-call team.

3. **Problem Launch Notifier**: Triggered when a ITIL Problem is promoted (5 similar incidents in 7 days detected). Notifies the problem management team.

### Why n8n instead of sending emails directly from the backend?

- **Separation of concerns**: The backend handles logic; n8n handles communication. You can change the notification channel (email → Teams → Slack) without touching backend code.
- **Visual editing**: Business users can modify workflows without code.
- **Retry handling**: n8n automatically retries failed webhook deliveries.
- **Planned**: The roadmap includes replacing SMTP with Microsoft Teams via OAuth in n8n.

---

## 10. SLA MANAGEMENT

### What is SLA in ITSM context?

SLA = Service Level Agreement. In IT support, it defines the maximum time allowed to respond to or resolve a ticket based on its priority:

| Priority | Response time | Resolution time |
|----------|--------------|-----------------|
| Critical | 1 hour | 4 hours |
| High | 4 hours | 8 hours |
| Medium | 8 hours | 24 hours |
| Low | 24 hours | 72 hours |

### How the platform tracks SLA

Each ticket has:
- `sla_first_response_due_at` — when the first response must happen
- `sla_resolution_due_at` — when the ticket must be resolved
- `sla_status` — `on_track` / `at_risk` / `breached`
- `sla_remaining_minutes` — minutes left before breach
- `sla_elapsed_minutes` — how long it's been open

### The proactive SLA monitor

`sla_monitor.py` runs as a background async task every 300 seconds (5 minutes). It:
1. Queries all open tickets
2. For each ticket: calculates `elapsed / total`
3. If ratio ≥ 0.75 (75% of SLA consumed) → marks as "at risk" and triggers n8n notification
4. If `resolution_due_at < now` → marks as "breached"
5. Uses a 60-minute deduplication window so it doesn't send the same alert twice

### AI SLA Risk

Beyond the simple time-based SLA, there is an AI model (`ai_sla_risk.py`) that predicts which tickets are **likely** to breach based on historical patterns. This is the "shadow mode" feature — it runs predictions without taking action, letting you validate accuracy before enabling it for real.

---

## 11. ITIL CONCEPTS

ITIL (Information Technology Infrastructure Library) is the global framework for IT service management. Your platform implements ITIL 4 practices.

### Incident Management

An **incident** is an unplanned interruption to an IT service. Examples: "my email is not working", "I cannot connect to the VPN".

In the platform:
- Ticket type = `incident`
- Goal: restore service as fast as possible (SLA-driven)
- The AI classifier automatically detects incident patterns and suggests resolutions based on past resolved incidents

### Problem Management

A **problem** is the root cause of one or more incidents. If 5 people report email issues in a week, there is probably one root cause (a server configuration).

In the platform:
- The system detects when 5+ similar incidents occur in 7 days
- It creates a `Problem` record linking all related incidents
- The problem page shows the pattern, AI-generated root cause hypothesis, and resolution recommendation
- This is ITIL's "reactive problem management" process

### Service Request Management

A **service request** is a formal request for something standard. Examples: "I need a new laptop", "please create a VPN account for me".

In the platform:
- Ticket type = `service_request`
- The `service_requests.py` AI module provides specialized handling for common request categories
- The `taxonomy.py` module classifies requests into a structured ITIL taxonomy

### Change Management

A **change** is a modification to IT infrastructure. The platform supports change ticket types and integrates with Jira's change management fields.

### The ITIL Service Desk

The platform IS the service desk interface. It provides:
- **Single point of contact** for users
- **Ticket lifecycle management** (open → in progress → resolved → closed)
- **Knowledge base** (past solutions reused via RAG)
- **Performance metrics** (MTTR, SLA compliance rate, agent performance)

---

## 12. ISO STANDARDS

### ISO 27001 — Information Security Management System (ISMS)

ISO 27001 is not a checklist of technical controls — it is a management framework. It defines how an organization should **manage** information security. The technical controls are in Annex A.

**What you implemented (Annex A controls)**:

| Control | Your Implementation |
|---------|-------------------|
| A.9 — Access Control | RBAC (4 roles: admin, agent, user, viewer), every route protected, role changes audited |
| A.9.4 — Brute-force | Account lockout after 5 failures, 15-min lockout, events logged |
| A.10 — Cryptography | bcrypt for passwords, JWT with HS256, algorithm allowlist blocks `none` attack |
| A.12.4 — Audit Logging | `security_events` table: all logins, failures, role changes, exports — immutable append-only |
| A.12.4 — Log Retention | `AUDIT_LOG_RETENTION_DAYS=365`, auto-purge on startup |
| A.13 — Network Controls | CORS allowlist, TrustedHostMiddleware, rate limiting, X-Forwarded-For spoofing protection |
| A.14 — Secure Development | SameSite=Strict cookies, CSP header, X-Frame-Options: DENY, HSTS in production |
| A.8.2 — Data Classification | CONFIDENTIAL (tickets, users), RESTRICTED (audit logs) labels in config |

**Key concept for defense**: ISO 27001 certification requires these controls to be **documented, implemented, monitored, and reviewed**. Your `/api/admin/compliance-summary` endpoint and `/admin/security` page serve as the monitoring dashboard.

### ISO 42001 — AI Management System (AIMS)

ISO 42001 (published 2023) is the first international standard for managing AI systems responsibly. It requires organizations to treat AI systems with the same rigor as other critical systems.

**Key clauses and your implementation**:

| Clause | Requirement | Your Implementation |
|--------|-------------|-------------------|
| 6.1 | AI risk treatment | `human_reviewed_at` + `override_reason` on every AI decision — humans can review and correct |
| 8.4 | AI system documentation | `AI_WORKFLOW_README.md`, `AUTONOMOUS_REVIEW_REPORT.md` |
| 9.1 | Performance monitoring | Confidence bands tracked per decision, `human_review_rate_pct` metric |
| 9.1 | Human oversight | `POST /api/ai/classification-logs/{id}/human-review` endpoint |
| 10.1 | Continual improvement | Feedback loop (thumbs up/down), analytics on recommendation utility |

**Key concept for defense**: The spec only asked for "notions" of ISO 42001. You implemented actual measurable controls. The key principle is **human oversight over AI decisions** — no AI action is irreversible, and every decision can be reviewed and overridden.

---

## 13. FULL REQUEST LIFECYCLE

### Trace: Agent asks the chatbot "How do I fix this network error?"

**Step 1 — Frontend (ticket-chatbot.tsx)**
- User types message, clicks send
- `handleSend()` called, builds `{ message, ticket_id, history: last 5 messages }`
- `apiFetch("/ai/chat", { method: "POST", body: JSON.stringify(payload) })`
- Sets `isLoading = true`, spinner appears

**Step 2 — Network**
- Browser sends: `POST http://localhost:8000/api/ai/chat`
- Cookie `tw_access` attached automatically (HttpOnly cookie)

**Step 3 — FastAPI middleware stack**
- Rate limit check: IP has not exceeded 30 AI requests/min ✓
- JWT decoded from cookie → user extracted
- Route matched: `ai.py` → `chat()` function

**Step 4 — orchestrator.py: handle_chat()**
```
1. intent = detect_intent("How do I fix this network error?")
   → keyword "fix", "error" → RECOMMENDATION_LISTING
   
2. conversation_policy: is this a follow-up? No → fresh context
   
3. ticket = load ticket data from DB
   
4. similar = unified_retrieve(db, query="network error fix", top_k=5)
   → embed query → pgvector search → top 5 KB chunks
   
5. resolution_advisor.generate(ticket, similar_tickets, kb_results)
   → scores confidence: strong match found (0.78) → evidence_action
   → calls LLM with grounded prompt
   
6. format response as ChatResponse schema
```

**Step 5 — LLM call (llm.py)**
```
POST http://localhost:11434/api/generate
{
  "model": "qwen3:4b",
  "prompt": "You are an ITSM assistant. Ticket: [data]. Similar resolved tickets: [top 5]. Question: How do I fix this? Answer in JSON: {solution, steps, confidence}",
  "stream": false
}
```
Response in ~3 seconds.

**Step 6 — Response back to frontend**
- FastAPI returns `ChatResponse` JSON
- `apiFetch` resolves, `setMessages(prev => [...prev, assistantMsg])`
- React re-renders, new message bubble appears
- `isLoading = false`, spinner disappears

Total time: ~3-5 seconds (dominated by LLM inference)

---

## 14. DEFENSE QUESTIONS

### Architecture questions

**Q: Why did you separate the frontend and backend instead of using a monolith?**
A: The separation (called a "decoupled architecture") allows the frontend and backend to evolve independently. The backend exposes a REST API that could serve a mobile app, a Jira plugin, or an n8n workflow — not just our web interface. It also allows separate deployment and scaling: if the AI endpoint is slow, I can scale only the backend workers without touching the frontend.

**Q: Why PostgreSQL and not MongoDB or a pure vector database?**
A: ITSM data is highly structured and relational — tickets belong to users, SLA records belong to tickets, notifications belong to users. MongoDB's schemaless approach would lose the referential integrity guarantees I need. For vector search, adding pgvector to PostgreSQL means I don't need to maintain a separate Qdrant or Pinecone instance — one database handles both structured queries and semantic search.

**Q: What is the scalability bottleneck?**
A: The LLM inference running on Ollama locally. In production, this would be replaced by a model API (Anthropic, Azure OpenAI) or a dedicated GPU inference server. The rest of the stack (FastAPI + PostgreSQL + Redis) can scale horizontally with load balancers. The two-level cache (L1 in-memory + L2 Redis) significantly reduces the LLM call rate.

### AI questions

**Q: What is RAG and why is it better than fine-tuning the model?**
A: RAG (Retrieval-Augmented Generation) keeps the model general and augments it with domain-specific context at query time. Fine-tuning bakes knowledge into the model weights — it requires expensive GPU training, and the knowledge becomes stale as new tickets accumulate. With RAG, new resolved tickets are automatically embedded and available for retrieval the same day. RAG is also more transparent: you can show exactly which retrieved documents influenced the answer.

**Q: How do you measure the quality of AI recommendations?**
A: Three ways. First, the confidence band system — recommendations below 0.25 confidence are displayed as "general knowledge" without an Apply button. Second, user feedback: agents can thumbs up/down any recommendation; this feeds the `ai_solution_feedback` table and the analytics page shows the useful rate over time. Third, ISO 42001 human oversight: agents can mark decisions as reviewed and override them, creating a correction dataset.

**Q: What prevents the AI from hallucinating?**
A: The RAG grounding is the main protection. The LLM prompt explicitly says "answer ONLY based on the provided context". If no relevant context is retrieved (similarity score below threshold), the system returns a `no_strong_match` response with a manual triage message rather than letting the LLM invent an answer. The 4-level trust hierarchy enforces this: only `evidence_action` (strong match) gets an Apply button.

**Q: What is an embedding and why use cosine similarity?**
A: An embedding is a dense vector representation of text in a high-dimensional space (768 dimensions) where semantic similarity corresponds to geometric proximity. Cosine similarity measures the angle between vectors — it captures directional similarity regardless of magnitude, which works better for text than Euclidean distance because it focuses on what the text is *about* rather than how long it is.

### Security questions

**Q: Why SameSite=Strict instead of Lax?**
A: SameSite=Lax allows cookies to be sent on top-level navigations (clicking a link). Strict means the cookie is never sent on any cross-site request, including navigation. Since our SPA does all navigation via client-side routing and API calls — never by following links from other sites — Strict gives us complete CSRF protection with no usability cost. The one exception is the Google OAuth state cookie, which must be Lax because it needs to survive the cross-site redirect from Google back to our callback URL.

**Q: What is the ACCOUNT_LOCKED / account_unlocked flow?**
A: After 5 failed login attempts, `locked_until` is set to now + 15 minutes. Any attempt during the lockout returns HTTP 423 with remaining minutes, and a `login_blocked` event is written to `security_events`. When the lockout naturally expires (next login attempt after the 15 minutes), the code detects `locked_until ≤ now`, clears both fields, and emits `account_unlocked` before proceeding with password verification. Admins can also force-unlock early via `POST /api/users/{id}/unlock`.

**Q: What is the difference between authentication and authorization?**
A: Authentication = proving who you are (login with email+password, JWT verification). Authorization = determining what you're allowed to do (RBAC roles). In the platform: `get_current_user` dependency handles authentication (decodes JWT, loads user). `require_roles()` and `require_admin` dependencies handle authorization (check user.role against allowed roles).

### ITIL/ISO questions

**Q: What is the difference between an Incident and a Problem in ITIL?**
A: An incident is a single unplanned service interruption that needs to be resolved quickly (restore service). A problem is the underlying root cause of one or more incidents, investigated to prevent recurrence. In the platform: incidents are regular tickets; problems are promoted automatically when 5+ similar incidents occur in 7 days. The AI generates a root cause hypothesis for each problem using RAG over the linked incident tickets.

**Q: How does your platform support ISO 27001 without being certified?**
A: ISO 27001 certification requires a formal audit by an accredited certification body. The platform implements the technical controls from Annex A (access control, cryptography, audit logging, network security, secure development) and provides the monitoring infrastructure (compliance summary, security events dashboard). This establishes the technical foundation for certification — the organizational elements (risk assessment, management review, policies) would be the DSI's responsibility in a real deployment.

**Q: Why does ISO 42001 matter for an ITSM platform?**
A: Because the platform makes automated decisions that affect IT operations — ticket classification, priority assignment, routing suggestions. If the AI systematically misclassifies a certain type of ticket (bias), it could delay critical incidents. ISO 42001 requires that AI decisions be explainable (hence the `reasoning` field), traceable (hence `model_version` and `ai_classification_logs`), and subject to human oversight (hence the review/override endpoint). For a DSI processing potentially sensitive service requests, this governance is essential.

### Technical implementation questions

**Q: Explain the two-level cache architecture.**
A: Level 1 is Python's `@lru_cache` — stored in the process memory, instant retrieval, but lost on restart and not shared across workers. Level 2 is Redis — shared across all Uvicorn workers, survives restarts, TTL-based expiry. For embeddings: the SHA256 hash of the input text is the cache key. The same text always produces the same embedding, so if Redis has it, we skip the Ollama call entirely. The Redis TTL is 24 hours, matching the acceptable staleness for embedding vectors.

**Q: How does Alembic chain migrations?**
A: Each migration file has a `down_revision` pointing to the previous migration. This creates a linked list: `0001 → 0002 → ... → 0035 → 0036`. `alembic upgrade head` starts from the current database version (stored in the `alembic_version` table), finds the migration with that revision ID as `down_revision`, and applies `upgrade()` forward until it reaches `head`. This guarantees the database schema always matches the code's expectations.

**Q: What is the difference between a Pydantic model and a SQLAlchemy model?**
A: SQLAlchemy models define database tables — they map Python classes to SQL tables, with each attribute corresponding to a column. They are used for DB read/write operations in the service layer. Pydantic models (schemas) define the shape of data entering and leaving the API — they validate input, coerce types, and serialize output. FastAPI uses Pydantic schemas for request body parsing and response serialization. The same data concept (e.g., "Ticket") has two representations: a SQLAlchemy model for DB storage and a Pydantic schema for API communication.

---

*This guide covers the full technical depth of the platform. Read it several times before your defense. The most important sections for the jury are 6 (AI Pipeline), 11 (ITIL), and 12 (ISO Standards).*
