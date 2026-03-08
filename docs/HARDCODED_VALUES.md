# Hardcoded Values Audit

Last updated: 2026-03-06

This document lists what is hardcoded and what is not, with an explicit scope.

## Scope

- `frontend/app/problems/[id]/page.tsx`
- `frontend/lib/problems-api.ts`
- `frontend/lib/api.ts`
- `backend/app/core/config.py`
- README-level architecture/config guidance

## Hardcoded (Intentional)

1. Problem status order in UI:
   - File: `frontend/app/problems/[id]/page.tsx`
   - Constant: `PROBLEM_STATUSES = ["open", "investigating", "known_error", "resolved", "closed"]`
   - Why: keeps status dropdown order stable and predictable.

2. Problem status presentation mapping:
   - File: `frontend/app/problems/[id]/page.tsx`
   - Constant: `PROBLEM_STATUS_CONFIG`
   - Why: visual style + bilingual labels for known status enum values.

3. Fallback AI confidence scoring:
   - File: `frontend/lib/problems-api.ts`
   - Constants:
     - `PROBLEM_AI_FALLBACK_CONFIDENCE_START = 82`
     - `PROBLEM_AI_FALLBACK_CONFIDENCE_STEP = 6`
     - `PROBLEM_AI_FALLBACK_CONFIDENCE_MIN = 55`
   - Why: deterministic fallback when backend returns plain suggestion text without explicit confidence.

4. Backend protocol/security defaults:
   - File: `backend/app/core/config.py`
   - Values: `JWT_ALGORITHM = "HS256"` and validation rules for weak/default secrets.
   - Why: stable security baseline.

## Hardcoded (Config Defaults, Intended for Override)

1. Frontend API fallback:
   - File: `frontend/lib/api.ts`
   - Value: `API_BASE` fallback to `http://localhost:8000/api`
   - Override: `NEXT_PUBLIC_API_URL`.

2. Backend local-development defaults:
   - File: `backend/app/core/config.py`
   - Examples: `DATABASE_URL`, `FRONTEND_BASE_URL`, `CORS_ORIGINS`, `OLLAMA_BASE_URL`.
   - Override: `backend/.env`.

3. Backend weak dev secret default:
   - File: `backend/app/core/config.py`
   - Value: `JWT_SECRET = "change-me"`
   - Override required for real deployments; production guardrails reject weak secrets.

## Not Hardcoded (Dynamic)

1. Problem/ticket content:
   - Source: API/database (`fetchProblem`, ticket lists, problem counters, linked tickets).
   - Includes: title, assignee, counts, timestamps, status updates.

2. Assignee options:
   - Source: `GET /users/assignees` at runtime.
   - UI only renders fetched data.

3. AI suggestions with model confidence:
   - Source: backend `suggestions_scored` payload when provided.
   - Fallback constants are used only if scored confidence is missing.

4. Environment-specific runtime behavior:
   - Source: `.env` values in backend/frontend.
   - Includes DB connection, JWT secret, Jira credentials, SMTP credentials, base URLs.

## Unnecessary Hardcode Removed in This Update

1. Duplicate fallback confidence formula in problem detail page:
   - Removed from `frontend/app/problems/[id]/page.tsx`.
   - Replaced with shared `scoreProblemSuggestions(...)` from `frontend/lib/problems-api.ts`.

2. Repeated inline status literals in status dropdown:
   - Replaced with a single `PROBLEM_STATUSES` constant and mapped rendering.
