# Sprint Backlog

## Sprint

- Sprint name: Sprint `Jira Sync + RAG Hardening`
- Dates: `2026-02-19` to `2026-02-19`
- Sprint goal: Stabilize Jira sync/resync with pgvector DB and remove schema-breaking data issues.

## Selected stories

| Story ID | Story | Owner | Status |
| --- | --- | --- | --- |
| US-001 | AI ticket draft flow | Team | Done |
| US-002 | Comment-aware recommendations | Team | Done |
| US-003 | Data query response paths | Team | Done |
| US-004 | Jira sync/resync safety and DB consistency | Team | Done |

## Tasks

| Task ID | Linked Story | Task | Owner | Estimate | Status |
| --- | --- | --- | --- | --- | --- |
| T-001 | US-004 | Move backend to pgvector DB (`localhost:55432`) and validate extension/table presence | Team | 0.5d | Done |
| T-002 | US-004 | Push/update local TW tickets to Jira and run manual reconcile verification | Team | 0.5d | Done |
| T-003 | US-003 | Fix `/api/tickets` crash from oversized Jira tags (schema-safe normalization) | Team | 0.5d | Done |
| T-004 | US-004 | Remove non-essential local mirrored rows and keep core TW baseline for dashboard clarity | Team | 0.5d | Done |
| T-005 | US-004 | Document intentional constants vs env-config values in backend docs | Team | 0.25d | Done |

## Notes

- Keep API payloads stable.
- Tag limits are now centralized in `app/core/ticket_limits.py` and enforced during Jira mapping.
- Intentional constants are documented in `backend/README.md` under "Intentional Constants".
