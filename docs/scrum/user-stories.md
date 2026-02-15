# User Stories

Format:

- As a `<role>`, I want `<capability>`, so that `<outcome>`.

## Stories

### US-001

- As a support agent, I want AI-generated ticket drafts from chat, so that I can create tickets faster.
- Acceptance criteria:
  - Chat response can return a valid ticket draft payload.
  - If create intent is ambiguous, action remains non-forced.
  - Draft includes title, description, priority, category, tags, and assignee when available.

### US-002

- As an operations lead, I want recurring problem solution hints based on past comments, so that we resolve repeated incidents faster.
- Acceptance criteria:
  - System analyzes relevant historical ticket comments.
  - Output includes at least one actionable recommendation when data exists.
  - Recommendations stay in the current response language (FR/EN).

### US-003

- As a team member, I want analytics queries in natural language, so that I can get quick operational metrics.
- Acceptance criteria:
  - Supports status, priority, category, assignee, and time-window filters.
  - Supports count/list/MTTR/reassignment/resolution-rate requests.
  - Ticket detail lookup by ticket ID is supported.
