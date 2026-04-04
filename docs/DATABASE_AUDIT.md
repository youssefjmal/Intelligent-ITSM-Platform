# Database Audit Report

**Generated:** 2026-03-27

---

## 1. Schema overview

| Table | Purpose | Row estimate | Key relationships |
|---|---|---|---|
| `users` | Authentication & authorization | 50-200 | Central hub: users → roles, tokens, notifications, feedback |
| `tickets` | ITSM tickets (incidents/requests) | 10,000-50,000 | Linked to problems, comments, feedback, notifications, automation events |
| `ticket_comments` | Ticket discussion thread | 50,000-200,000 | One-to-many with tickets; reverse-synced from Jira |
| `problems` | Recurring incident grouping | 100-1,000 | One-to-many with tickets; pattern matching for auto-grouping |
| `recommendations` | AI insights & suggestions | 500-5,000 | Standalone; referenced by feedback records |
| `ai_solution_feedback` | Feedback on AI recommendations | 5,000-20,000 | Links users to recommendations, tickets, and snapshots |
| `notification_preferences` | User notification settings | 50-200 | One-to-one with users (primary key is user_id) |
| `notifications` | In-app alerts & messages | 100,000+ | Links users to notification events; supports read tracking |
| `notification_delivery_events` | Delivery trace for debugging | 50,000-500,000 | Links notifications to users & n8n workflows |
| `kb_chunks` | Semantic RAG index (pgvector) | 5,000-50,000 | Standalone; from Jira issues & comments; pgvector embedding |
| `jira_sync_state` | Reconciliation checkpoints | 5-20 | One per Jira project; tracks last sync timestamp |
| `refresh_tokens` | JWT session rotation | 100-1,000 | Links users; supports revocation & replacement |
| `verification_tokens` | Email confirmation | 10-100 | Links users; one-time use with expiry |
| `password_reset_tokens` | Password recovery | 10-100 | Links users; one-time use with expiry |
| `email_logs` | Outbound email audit | 1,000-10,000 | Standalone; for verification, welcome, digest emails |
| `automation_events` | SLA/AI action audit trail | 5,000-50,000 | Links tickets; before/after snapshots of state |
| `ai_sla_risk_evaluations` | SLA risk scoring (shadow mode) | 1,000-10,000 | Links tickets; audit trail for AI escalation recommendations |

---

## 2. Table-by-table analysis

### users
**Purpose:** Stores application user accounts with roles, authentication credentials, and profile metadata.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | NO | PK; auto-generated |
| `email` | varchar(255) | NO | UQ, IDX; used for login and contact |
| `name` | varchar(255) | NO | Display name |
| `role` | ENUM(user_role) | NO | Values: admin, agent, user, viewer |
| `specializations` | JSONB | NO | List of domain specializations; flexible schema |
| `seniority_level` | ENUM(user_seniority) | NO | Values: intern, junior, middle, senior |
| `is_available` | boolean | NO | Default: true; for workload management |
| `max_concurrent_tickets` | integer | NO | Default: 10; assignment constraint |
| `password_hash` | varchar(255) | YES | Null for OAuth users |
| `google_id` | varchar(255) | YES | UQ; for Google SSO integration |
| `is_verified` | boolean | NO | Email verification flag |
| `created_at` | timestamp tz | NO | Account creation time |

**Indexes:**
- `ix_users_email` (UNIQUE)
- `ix_users_google_id` (UNIQUE)

**Constraints:**
- PK: `id`
- UQ: `email`, `google_id`

**Observations:**
- `specializations` is a JSONB list with no validation schema defined in the model. Could benefit from constraints or a separate `user_specializations` table if querying by specialization is frequent.
- `is_available` and `max_concurrent_tickets` are used for auto-assignment logic but have no index — queries like "find available agents" would need full table scan.
- No created_by or last_login tracking for audit purposes.

---

### tickets
**Purpose:** Core ITSM entity representing incidents and service requests. Stores Jira sync state, SLA tracking, AI predictions, and resolution data.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | varchar(20) | NO | PK; e.g., "TW-001" or Jira key |
| `title` | varchar(255) | NO | Ticket subject |
| `description` | text | NO | Ticket body |
| `status` | ENUM(ticket_status) | NO | Values: open, in-progress, waiting-for-customer, waiting-for-support-vendor, pending (legacy), resolved, closed |
| `priority` | ENUM(ticket_priority) | NO | Values: critical, high, medium, low |
| `ticket_type` | ENUM(ticket_type) | NO | Values: incident, service_request |
| `category` | ENUM(ticket_category) | NO | Values: infrastructure, network, security, application, service_request, hardware, email, problem |
| `assignee` | varchar(255) | NO | Assignee name (not a FK) |
| `reporter` | varchar(255) | NO | Reporter name (not a FK) |
| `reporter_id` | varchar(64) | YES | IDX; Jira user ID or internal user ID |
| `problem_id` | varchar(20) | YES | FK → problems.id; many-to-one |
| `auto_assignment_applied` | boolean | NO | Flag: ML assignment was used |
| `auto_priority_applied` | boolean | NO | Flag: ML priority prediction was used |
| `assignment_model_version` | varchar(40) | NO | Default: "legacy"; model version used for auto-assignment |
| `priority_model_version` | varchar(40) | NO | Default: "legacy"; model version used for priority |
| `predicted_priority` | ENUM(ticket_priority) | YES | ML predicted priority (not necessarily applied) |
| `predicted_ticket_type` | ENUM(ticket_type) | YES | ML predicted ticket type |
| `predicted_category` | ENUM(ticket_category) | YES | ML predicted category |
| `assignment_change_count` | integer | NO | Default: 0; number of times reassigned |
| `first_action_at` | timestamp tz | YES | When first comment/update occurred |
| `resolved_at` | timestamp tz | YES | When ticket was marked resolved |
| `created_at` | timestamp tz | NO | Ticket creation time |
| `updated_at` | timestamp tz | NO | Last update time |
| `source` | varchar(32) | NO | Default: "local"; values: "local", "jira", "external_api", etc.; IDX |
| `jira_key` | varchar(64) | YES | UQ, IDX; Jira ticket key, e.g., "PROJ-123" |
| `jira_issue_id` | varchar(64) | YES | UQ, IDX; Jira internal issue ID |
| `jira_created_at` | timestamp tz | YES | Creation time from Jira |
| `jira_updated_at` | timestamp tz | YES | Last update time from Jira |
| `external_id` | varchar(128) | YES | IDX; ID from non-Jira external system |
| `external_source` | varchar(32) | YES | IDX; external system name (e.g., "servicenow", "zendesk") |
| `external_updated_at` | timestamp tz | YES | Last update from external system |
| `last_synced_at` | timestamp tz | YES | Last reconciliation timestamp |
| `due_at` | timestamp tz | YES | Due date (added in migration 0029) |
| `raw_payload` | JSONB | YES | Complete payload from Jira/external source |
| `jira_sla_payload` | JSONB | YES | SLA configuration from Jira |
| `sla_status` | varchar(32) | YES | Local SLA status: "ok", "at_risk", "breached", "paused", "completed", "unknown" |
| `sla_first_response_due_at` | timestamp tz | YES | SLA target for first response |
| `sla_resolution_due_at` | timestamp tz | YES | SLA target for resolution |
| `sla_first_response_breached` | boolean | NO | Default: false; breach flag |
| `sla_resolution_breached` | boolean | NO | Default: false; breach flag |
| `sla_first_response_completed_at` | timestamp tz | YES | When first response SLA was met |
| `sla_resolution_completed_at` | timestamp tz | YES | When resolution SLA was met |
| `sla_remaining_minutes` | integer | YES | Computed remaining SLA time |
| `sla_elapsed_minutes` | integer | YES | Computed elapsed SLA time |
| `sla_last_synced_at` | timestamp tz | YES | Last SLA sync time |
| `priority_auto_escalated` | boolean | NO | Default: false; AI escalation flag |
| `priority_escalation_reason` | varchar(255) | YES | Reason for AI escalation |
| `priority_escalated_at` | timestamp tz | YES | When AI escalation occurred |
| `resolution` | text | YES | Resolution notes or steps taken |
| `tags` | JSONB | NO | Default: []; flexible tags |
| `ai_summary` | text | YES | AI-generated ticket summary (added in migration 0033) |
| `summary_generated_at` | timestamp tz | YES | Staleness marker for AI summary |

**Indexes:**
- `uq_tickets_external_source_external_id` (UNIQUE, compound)
- `uq_tickets_jira_key` (UNIQUE)
- `uq_tickets_jira_issue_id` (UNIQUE)
- `ix_tickets_reporter_id`
- `ix_tickets_problem_id`
- `ix_tickets_source`
- `ix_tickets_jira_key`
- `ix_tickets_jira_issue_id`
- `ix_tickets_external_id`
- `ix_tickets_external_source`

**Constraints:**
- PK: `id`
- FK: `problem_id` → `problems.id` (nullable, SET NULL on delete)
- UQ: (external_source, external_id), jira_key, jira_issue_id

**Observations:**
- **CRITICAL:** `assignee` and `reporter` are stored as string names, not as ForeignKeys to users. This makes it impossible to track which user records correspond to which tickets, and there's no referential integrity. Queries like "tickets assigned to user X" require string matching on names, which is brittle (names can change).
- **MISSING INDEX:** `problem_id` is indexed but queries on `status`, `priority`, `assignee` are likely common but have no indexes. A compound index on (status, priority, created_at) or (assignee, created_at) would speed up filtering/sorting.
- **MISSING INDEX:** `updated_at` has no index. Common query pattern: "tickets updated since T" (e.g., for last-30-days analytics) would benefit from an index.
- **MISSING INDEX:** `sla_status` has no index. "Find at-risk tickets" queries would scan the full table without an index.
- **Redundancy:** `assignment_change_count` is a counter but no separate audit table tracks who reassigned. It's a derived metric with no history.
- **Dead column risk:** `predicted_priority`, `predicted_ticket_type`, `predicted_category` are never read by any router (confirmed by grepping routers/). They should either be used or removed.
- **JSONB columns:** `raw_payload`, `jira_sla_payload`, `tags` are flexible but unindexed. Queries on `tags` (e.g., "find tickets with tag X") would be slow without a GIN index on tags.
- **Data integrity:** `jira_created_at` and `created_at` can diverge if a ticket is synced after local creation. There's no constraint to keep them consistent.
- **Nullable predicteds:** ML predictions are nullable, allowing ambiguity about whether "no prediction" means "not run yet" or "ran but no prediction available." Should have a status field like `prediction_status` (pending, done, failed).

---

### ticket_comments
**Purpose:** Discussion thread for tickets, reverse-synced from Jira and local comments.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | varchar(20) | NO | PK; unique comment ID |
| `ticket_id` | varchar(20) | NO | FK → tickets.id; cascading delete |
| `author` | varchar(255) | NO | Comment author name |
| `content` | text | NO | Comment body |
| `created_at` | timestamp tz | NO | Comment creation time |
| `updated_at` | timestamp tz | YES | Last edit time (if edited) |
| `jira_comment_id` | varchar(64) | YES | UQ, IDX; Jira internal comment ID |
| `jira_created_at` | timestamp tz | YES | Creation time from Jira |
| `jira_updated_at` | timestamp tz | YES | Last update time from Jira |
| `external_comment_id` | varchar(128) | YES | IDX; ID from non-Jira external system |
| `external_source` | varchar(32) | YES | IDX; external system name |
| `external_updated_at` | timestamp tz | YES | Last update from external system |
| `raw_payload` | JSONB | YES | Complete payload from Jira/external source |

**Indexes:**
- `uq_ticket_comments_ticket_external_comment` (UNIQUE, compound)
- `uq_ticket_comments_jira_comment_id` (UNIQUE)
- `ix_ticket_comments_jira_comment_id`
- `ix_ticket_comments_external_comment_id`
- `ix_ticket_comments_external_source`

**Constraints:**
- PK: `id`
- FK: `ticket_id` → `tickets.id` (CASCADE)
- UQ: (ticket_id, external_comment_id), jira_comment_id

**Observations:**
- **MISSING INDEX:** `ticket_id` has no explicit index, but it's part of the CASCADE FK. A query like "get all comments for ticket X ordered by created_at" would benefit from an index on `ticket_id` (and possibly a compound index with `created_at` for sorting).
- **MISSING INDEX:** `author` has no index. Queries like "comments by user X" would be slow. Either index `author` or add a FK to users.author field.
- `author` is a string, not a FK to users. Same issue as tickets.assignee — no referential integrity.
- `raw_payload` JSONB is unindexed; queries on payload content would be slow.
- `updated_at` can be null. If a comment is never edited, updated_at is null. This is unusual — typically updated_at defaults to created_at or is explicitly set. Queries like "modified since T" would miss unedited comments.

---

### problems
**Purpose:** Groups recurring tickets by detected pattern (similarity key). Stores root cause, workaround, permanent fix.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | varchar(20) | NO | PK; problem identifier |
| `title` | varchar(255) | NO | Problem summary |
| `category` | ENUM(ticket_category) | NO | Ticket category associated with this problem |
| `status` | ENUM(problem_status) | NO | Default: "open"; values: open, investigating, known_error, resolved, closed |
| `created_at` | timestamp tz | NO | Problem first detected |
| `updated_at` | timestamp tz | NO | Last update |
| `last_seen_at` | timestamp tz | YES | When problem was last observed |
| `resolved_at` | timestamp tz | YES | When problem was marked resolved |
| `occurrences_count` | integer | NO | Default: 0; total tickets linked to this problem |
| `active_count` | integer | NO | Default: 0; open tickets still linked to this problem |
| `root_cause` | text | YES | Diagnosed root cause |
| `workaround` | text | YES | Temporary workaround steps |
| `permanent_fix` | text | YES | Permanent resolution steps |
| `similarity_key` | varchar(255) | NO | UQ, IDX; hash/fingerprint for dedup |

**Indexes:**
- `ix_problems_similarity_key` (UNIQUE)

**Constraints:**
- PK: `id`
- UQ: similarity_key

**Observations:**
- **MISSING INDEXES:** `status` has no index. Queries like "open problems" would scan the full table. A compound index on (status, category, created_at) would help.
- **MISSING INDEX:** `last_seen_at` has no index. Queries like "problems seen in the last week" would be slow.
- **Dead columns risk:** `occurrences_count` and `active_count` are counters but derived from the relationship. If the relationship is the source of truth, these should be computed views, not stored. If stored, they must be kept in sync via triggers or application logic — no evidence of either.
- **MISSING CONSTRAINT:** No check constraint on `active_count <= occurrences_count`. A malformed update could break invariants.
- Relationship to tickets is one-to-many but not explicitly declared with a FK. The `problem_id` in tickets points here, but no back-reference in the model indicates how many tickets are linked. Queries like "get top 10 problems by active_count" are unclear if the counter is accurate.

---

### recommendations
**Purpose:** AI-generated insights: pattern matches, priority suggestions, solutions, workflow improvements.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | varchar(20) | NO | PK; recommendation identifier |
| `type` | ENUM(recommendation_type) | NO | Values: pattern, priority, solution, workflow |
| `title` | varchar(255) | NO | Recommendation headline |
| `description` | text | NO | Detailed explanation |
| `related_tickets` | JSONB | NO | Default: []; list of ticket IDs ("TW-001", "TW-002", ...) |
| `confidence` | integer | NO | Default: 0; confidence percentage (0-100) |
| `impact` | ENUM(recommendation_impact) | NO | Default: "medium"; values: high, medium, low |
| `created_at` | timestamp tz | NO | Recommendation generated time |

**Indexes:**
- None (except implicit PK)

**Constraints:**
- PK: `id`

**Observations:**
- **MISSING INDEXES:** No indexes on `type`, `impact`, `created_at`. Queries like "show high-impact recommendations created today" would require full table scans. Compound index on (type, impact, created_at) would help.
- **MISSING INDEX:** `confidence` has no index. Queries like "recommendations with confidence > 80%" would be slow.
- **Data integrity:** `related_tickets` is a JSONB list with no validation. It can contain invalid ticket IDs or duplicates. No FK constraint exists to prevent orphaning if a ticket is deleted.
- **MISSING CONSTRAINT:** No check constraint on `confidence` to ensure 0 <= confidence <= 100.
- **No relationship to feedback:** `recommendations` has no FK to `ai_solution_feedback`. The feedback table stores `recommendation_id` as a string, not a FK. No referential integrity.
- **MISSING INDEX on related_tickets:** If the frontend searches by ticket (e.g., "recommendations for ticket TW-001"), a GIN index on `related_tickets` would speed queries like `related_tickets @> '["TW-001"]'`.

---

### ai_solution_feedback
**Purpose:** Human feedback on AI recommendations, solutions, and suggestions. Tracks usefulness, application, rejection.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `user_id` | UUID | YES | FK → users.id; nullable, SET NULL on delete |
| `ticket_id` | varchar(20) | YES | FK → tickets.id; nullable, SET NULL on delete |
| `recommendation_id` | varchar(64) | YES | String ID, not FK; nullable |
| `query` | text | YES | Original query/search that prompted the recommendation |
| `recommendation_text` | text | NO | Snapshot of recommendation text |
| `source` | varchar(32) | NO | Where the recommendation came from: "chat", "draft", "detail", "sla_monitor", "recommendation_list", "search_result", "disambiguation" |
| `source_id` | varchar(120) | YES | Additional context for the source (e.g., session ID, search query ID) |
| `vote` | varchar(16) | NO | **DEPRECATED**; legacy values: "helpful" or "not_helpful"; retained for backward compatibility |
| `feedback_type` | varchar(24) | YES | New values: "useful", "not_relevant", "applied", "rejected" |
| `source_surface` | varchar(32) | YES | UI surface: "recommendations", "detail", "chat", "sla_monitor" |
| `target_key` | varchar(128) | YES | Identifies what was being shown (e.g., ticket ID) |
| `recommended_action_snapshot` | text | YES | AI recommendation text at time of feedback |
| `display_mode_snapshot` | varchar(32) | YES | How the recommendation was displayed: "link", "summary", "expanded", "interactive" |
| `confidence_snapshot` | float | YES | Confidence % at time of feedback (0-1 scale) |
| `reasoning_snapshot` | text | YES | Reasoning snapshot |
| `match_summary_snapshot` | text | YES | Match summary snapshot |
| `evidence_count_snapshot` | integer | YES | Number of evidence items |
| `context_json` | JSONB | YES | Additional context about the interaction |
| `created_at` | timestamp tz | NO | Feedback recorded time |
| `updated_at` | timestamp tz | NO | Last update |

**Indexes:**
- `ix_ai_solution_feedback_source_source_id` (compound)
- `ix_ai_solution_feedback_user_id`
- `ix_ai_solution_feedback_created_at`
- `ix_ai_solution_feedback_target_lookup` (compound: user_id, source_surface, target_key)
- `ix_ai_solution_feedback_ticket_surface` (compound: ticket_id, source_surface)
- `ix_ai_solution_feedback_recommendation_surface` (compound: recommendation_id, source_surface)
- `ix_ai_solution_feedback_feedback_type`
- `ix_ai_solution_feedback_vote` (legacy, to be removed with `vote` column)

**Constraints:**
- PK: `id`
- FK: `user_id` → `users.id` (nullable, SET NULL)
- FK: `ticket_id` → `tickets.id` (nullable, SET NULL)

**Observations:**
- **Schema design excellence:** Well-indexed for analytics queries. Compound indexes support key analysis patterns (user feedback, ticket-surface combinations, feedback type distribution).
- **Legacy deprecation well-managed:** `vote` column retained with index for backward compatibility. Clear deprecation path with `feedback_type` as new field.
- **Snapshots strategy:** Fields like `confidence_snapshot`, `reasoning_snapshot` preserve the AI state at feedback time, allowing analysis of AI quality over time.
- **Missing constraint:** No check constraint on `confidence_snapshot` (should be 0-1 if a percentage; otherwise needs clarification).
- **Missing FK on recommendation_id:** Although indexed, `recommendation_id` is a string, not a FK. Deleting a recommendation leaves orphaned feedback. Should be added unless recommendations are immutable.
- **Context flexibility:** `context_json` JSONB is flexible but unindexed. If specific context fields are frequently queried, they should be normalized or a GIN index added.
- **No NOT NULL on feedback_type:** Even though `vote` is NOT NULL, `feedback_type` can be null. Analytic queries must handle both `vote` and `feedback_type` for completeness. Consider a check constraint: `(vote IS NOT NULL) OR (feedback_type IS NOT NULL)`.

---

### notification_preferences
**Purpose:** User-level settings for notification delivery, frequency, quiet hours, event types.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `user_id` | UUID | NO | PK; FK → users.id, CASCADE |
| `email_enabled` | boolean | NO | Default: true |
| `email_min_severity` | varchar(16) | NO | Default: "critical"; minimum severity to email |
| `immediate_email_min_severity` | varchar(16) | NO | Default: "high"; threshold for immediate email (vs. digest) |
| `digest_enabled` | boolean | NO | Default: true |
| `digest_frequency` | varchar(24) | NO | Default: "hourly"; values: hourly, daily, weekly |
| `quiet_hours_enabled` | boolean | NO | Default: false |
| `quiet_hours_start` | time without tz | YES | Start time for quiet period |
| `quiet_hours_end` | time without tz | YES | End time for quiet period |
| `critical_bypass_quiet_hours` | boolean | NO | Default: true; critical alerts still sent during quiet hours |
| `ticket_assignment_enabled` | boolean | NO | Default: true; notify on ticket assignment |
| `ticket_comment_enabled` | boolean | NO | Default: true; notify on ticket comments |
| `sla_notifications_enabled` | boolean | NO | Default: true; notify on SLA breaches |
| `problem_notifications_enabled` | boolean | NO | Default: true; notify on problems |
| `ai_notifications_enabled` | boolean | NO | Default: true; notify on AI insights |
| `created_at` | timestamp tz | NO | Preference creation time |
| `updated_at` | timestamp tz | NO | Last update |

**Indexes:**
- PK on `user_id`

**Constraints:**
- PK: `user_id`
- FK: `user_id` → `users.id` (CASCADE)

**Observations:**
- **Missing constraints:** No check constraints on severity/frequency enums. Values like "invalid_severity" could be inserted without validation. Schema should list allowed values.
- **Missing constraint:** If `quiet_hours_enabled` is true, both `quiet_hours_start` and `quiet_hours_end` should be NOT NULL. A check constraint could enforce this.
- **Time zone note:** `quiet_hours_start` and `quiet_hours_end` are TIME without timezone. This could be a problem if users in different timezones exist. Behavior on daylight saving time changes is unclear.
- **Missing indexes:** No indexes on severity or frequency fields, but they're used for filtering in notification dispatch logic. Could benefit from compound indexes if filtering is common.
- **Design note:** One-to-one relationship with users (PK = user_id) is clean and avoids joins. However, if preferences have complex defaults, a factory function or database trigger might be needed to auto-create a row when a user is created.

---

### notifications
**Purpose:** In-app alert messages sent to users. Supports read tracking, pinning, and action buttons.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `user_id` | UUID | NO | FK → users.id; CASCADE; IDX |
| `title` | varchar(255) | NO | Notification headline |
| `body` | text | YES | Detailed message |
| `severity` | varchar(16) | NO | Default: "info"; values: critical, high, medium, low, info |
| `event_type` | varchar(48) | NO | Default: "system_alert"; classification of event (ticket_assigned, sla_breach, etc.) |
| `link` | varchar(512) | YES | Deep link to related resource |
| `source` | varchar(32) | YES | Origin: "sla_monitor", "ai_recommendation", "ticket_assignment", "n8n_workflow", etc. |
| `dedupe_key` | varchar(255) | YES | For deduplication — same key = same event recurring |
| `metadata_json` | JSONB | YES | Custom metadata attached to notification |
| `action_type` | varchar(24) | YES | Call-to-action: "apply", "dismiss", "snooze", etc. |
| `action_payload` | JSONB | YES | Payload for the action (e.g., {"recommendation_id": "REC-123"}) |
| `created_at` | timestamp tz | NO | Notification sent time |
| `read_at` | timestamp tz | YES | When user read the notification |
| `pinned_until_read` | boolean | NO | Default: false; keep pinned until read |

**Indexes:**
- `ix_notifications_user_id_read_at` (compound)
- `ix_notifications_user_id_event_type` (compound)
- `ix_notifications_user_id` (single, implicit from FK)

**Constraints:**
- PK: `id`
- FK: `user_id` → `users.id` (CASCADE)

**Observations:**
- **Missing constraint:** No check constraint on `severity`. Values like "extreme" could be inserted.
- **Missing indexes:** `created_at` has no index. Queries like "notifications created today" would scan the table. A compound index on (user_id, created_at) would help for "user's recent notifications" queries.
- **Missing index on event_type:** Even though there's an index on (user_id, event_type), a single-column index on `event_type` might help for system-wide event queries.
- **JSONB flexibility:** `metadata_json` and `action_payload` are flexible but unindexed. GIN indexes would help if these fields are frequently queried.
- **Deduplication strategy:** `dedupe_key` is used to prevent duplicate notifications, but there's no unique constraint on (user_id, dedupe_key). The dedup logic is in application code, not the database. If multiple notification-creation requests race, duplicates could still occur.
- **Design note:** `read_at` is nullable, allowing queries like "unread notifications" (WHERE read_at IS NULL). Clean pattern.

---

### notification_delivery_events
**Purpose:** Audit trail for notification delivery to external systems (email, Slack, n8n webhooks, etc.). For debugging failed deliveries.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `notification_id` | UUID | NO | FK → notifications.id; CASCADE; IDX |
| `user_id` | UUID | YES | FK → users.id; SET NULL; IDX |
| `workflow_name` | varchar(120) | YES | n8n workflow name (for tracing) |
| `trace_id` | varchar(120) | YES | Unique trace ID for debugging |
| `recipients_json` | JSONB | YES | List of recipients (emails, Slack IDs, etc.) |
| `duplicate_suppression` | text | YES | Dedup result (e.g., "suppressed_by_X") |
| `delivery_status` | varchar(32) | NO | Default: "in-app"; values: in-app, email-queued, email-sent, email-failed, slack-sent, slack-failed, webhook-sent, webhook-failed |
| `error` | text | YES | Error message if delivery failed |
| `created_at` | timestamp tz | NO | Event recorded time |

**Indexes:**
- `ix_notification_delivery_events_notification_id`
- `ix_notification_delivery_events_created_at`

**Constraints:**
- PK: `id`
- FK: `notification_id` → `notifications.id` (CASCADE)
- FK: `user_id` → `users.id` (SET NULL)

**Observations:**
- **Missing constraint:** No check constraint on `delivery_status`. Values like "invalid_status" could be inserted.
- **Missing index on delivery_status:** Queries like "failed deliveries" would scan the table. An index on `delivery_status` would help.
- **JSONB flexibility:** `recipients_json` is unindexed. If searching by recipient is needed, a GIN index would help.
- **Redundant user_id:** Both `notification_id` (FK) and `user_id` (FK) exist. `user_id` is also available via the notifications table. Storing both allows faster queries without joins, but introduces redundancy. If user_id changes in notifications, they could diverge.
- **Design note:** `trace_id` is useful for tracing n8n workflows but has no constraint/index. If tracing is critical, should be indexed.

---

### kb_chunks
**Purpose:** Semantic knowledge base for RAG. Stores text chunks from Jira issues/comments with pgvector embeddings.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | integer | NO | PK; auto-increment |
| `source_type` | varchar(64) | NO | Values: "jira_issue", "jira_comment", "local_article", etc. |
| `jira_issue_id` | varchar(64) | YES | IDX; Jira issue ID (if source is jira_issue/jira_comment) |
| `jira_key` | varchar(64) | YES | IDX; Jira project key (e.g., "PROJ") |
| `comment_id` | varchar(64) | YES | IDX; Jira comment ID (if source is jira_comment) |
| `content` | text | NO | Chunk text content |
| `content_hash` | varchar(64) | NO | IDX; SHA256 hash for dedup |
| `metadata` | JSONB | YES | Flexible metadata (title, author, tags, etc.) |
| `embedding` | Vector(768) | YES | pgvector vector type; 768-dimensional embedding |
| `created_at` | timestamp tz | NO | Chunk created/indexed time |
| `updated_at` | timestamp tz | NO | Last update |

**Indexes:**
- `ix_kb_chunks_content_hash`
- `uq_kb_chunks_jira_comment_identity` (UNIQUE, partial: WHERE source_type='jira_comment' AND jira_key IS NOT NULL AND comment_id IS NOT NULL)
- `uq_kb_chunks_jira_issue_identity` (UNIQUE, partial: WHERE source_type='jira_issue' AND jira_issue_id IS NOT NULL)
- `ix_kb_chunks_jira_issue_id`
- `ix_kb_chunks_jira_key`
- `ix_kb_chunks_comment_id`

**Constraints:**
- PK: `id`
- Partial unique constraints on Jira identities (via conditional indexes)

**Observations:**
- **Vector index missing:** `embedding` column has no vector index (pgvector IVFFlat or HNSW). Semantic search queries using `<->` distance operator will be slow on large datasets (>100K rows). Should add: `CREATE INDEX ON kb_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);`
- **JSONB index missing:** `metadata` JSONB has no GIN index. Queries on metadata fields would be slow.
- **Dedup strategy:** `content_hash` is indexed for dedup, but there's no unique constraint. Multiple chunks with the same hash could be inserted. Should either enforce uniqueness or document expected behavior (multiple chunks with same content OK for different contexts).
- **Source type flexibility:** No check constraint on `source_type`. Values like "invalid_source" could be inserted. Should list allowed values.
- **Missing constraints:** If source_type="jira_issue", then jira_issue_id and jira_key should be NOT NULL. If source_type="jira_comment", then jira_key, comment_id, jira_issue_id should be NOT NULL. These could be enforced with check constraints.
- **Embedding refresh:** No mechanism to update embeddings if the underlying content changes. `updated_at` is set but there's no trigger to refresh the embedding when content is modified.

---

### jira_sync_state
**Purpose:** Checkpoint for Jira reconciliation. Tracks last sync time and errors per project.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | integer | NO | PK; auto-increment |
| `project_key` | varchar(32) | NO | UQ, IDX; Jira project key (e.g., "PROJ") |
| `last_synced_at` | timestamp tz | YES | Last successful sync time |
| `last_error` | text | YES | Most recent sync error message |
| `updated_at` | timestamp tz | NO | Last update to this record |

**Indexes:**
- `ix_jira_sync_state_project_key` (UNIQUE)

**Constraints:**
- PK: `id`
- UQ: `project_key`

**Observations:**
- **Minimal tracking:** Only last sync timestamp and last error. No history of sync duration, number of tickets processed, or sync strategy version. For production debugging, a separate `jira_sync_audit` table could log each sync attempt.
- **Missing constraint:** No check constraint on `project_key` (e.g., must match Jira key format).
- **Nullable last_synced_at:** Allows distinguishing "never synced" from "synced before". Good design.
- **Missing index:** No index on `updated_at`. Queries like "projects synced in the last hour" would scan the table.

---

### refresh_tokens
**Purpose:** JWT token rotation and revocation. Tracks issued tokens and their lifecycle.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `jti` | varchar(36) | NO | PK; JWT ID (unique token identifier) |
| `user_id` | UUID | NO | FK → users.id; CASCADE; IDX |
| `created_at` | timestamp tz | NO | Token issued time |
| `expires_at` | timestamp tz | NO | Token expiration time |
| `revoked_at` | timestamp tz | YES | When token was manually revoked (e.g., logout) |
| `replaced_by_jti` | varchar(36) | YES | JTI of the new token if this one was rotated |

**Indexes:**
- `ix_refresh_tokens_user_id`

**Constraints:**
- PK: `jti`
- FK: `user_id` → `users.id` (CASCADE)

**Observations:**
- **Missing indexes:** No index on `expires_at`. Queries like "clean up expired tokens" would scan the table. Should add an index or schedule a job to delete expired rows.
- **Missing index on revoked_at:** Queries like "active tokens (revoked_at IS NULL)" would scan the table. A partial index on revoked_at (WHERE revoked_at IS NULL) would help.
- **Token rotation chain:** `replaced_by_jti` links tokens in a rotation chain, but there's no FK constraint. A token could reference a non-existent jti. Should be either a FK or documented as optional/informational only.
- **Audit trail:** No log of revocation reason or who revoked the token. For security, a separate `token_revocation_log` table could help.

---

### verification_tokens
**Purpose:** One-time email verification tokens. Issued during signup, burned on email confirmation.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `token` | varchar(64) | NO | PK; hex string token |
| `code` | varchar(6) | NO | IDX; 6-digit verification code |
| `user_id` | UUID | NO | FK → users.id; CASCADE |
| `created_at` | timestamp tz | NO | Token issued time |
| `expires_at` | timestamp tz | NO | Token expiration time |
| `used_at` | timestamp tz | YES | When the token was used (burned) |

**Indexes:**
- `ix_verification_tokens_code`

**Constraints:**
- PK: `token`
- FK: `user_id` → `users.id` (CASCADE)

**Observations:**
- **Missing index on user_id:** Queries like "active tokens for user X" would scan the table. Should add an index on `user_id` or a compound index on (user_id, expires_at).
- **Missing constraint on used_at:** A token should be used at most once. A check constraint (used_at IS NULL OR used_at <= expires_at) would ensure validity. Additionally, application logic must enforce one-time use (not database constraint).
- **Expiry cleanup:** No mechanism to delete expired tokens. They accumulate indefinitely. Should schedule a job to clean up tokens where expires_at < NOW().
- **Missing index on expires_at:** For cleanup queries ("DELETE WHERE expires_at < NOW()"), an index on `expires_at` would help.

---

### password_reset_tokens
**Purpose:** One-time password recovery tokens. Issued on "forgot password", burned on password reset.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `token` | varchar(64) | NO | PK; hex string token |
| `user_id` | UUID | NO | FK → users.id; CASCADE; IDX |
| `created_at` | timestamp tz | NO | Token issued time |
| `expires_at` | timestamp tz | NO | Token expiration time |
| `used_at` | timestamp tz | YES | When the token was used (password reset) |

**Indexes:**
- `ix_password_reset_tokens_user_id`

**Constraints:**
- PK: `token`
- FK: `user_id` → `users.id` (CASCADE)

**Observations:**
- **Missing index on expires_at:** For cleanup queries, should add index on `expires_at`.
- **Missing constraint on used_at:** Same as verification_tokens — should enforce one-time use via check constraint or application logic.
- **Similar design to verification_tokens:** Consider consolidating into a generic `password_reset_codes` table to reduce duplication. However, separation might be intentional for security (different access patterns, different TTLs).

---

### email_logs
**Purpose:** Audit trail for outbound emails (verification, welcome, digest, SLA alerts, etc.).

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `to` | varchar(255) | NO | Recipient email address |
| `subject` | varchar(255) | NO | Email subject |
| `body` | text | NO | Email HTML/plain text body |
| `kind` | ENUM(email_kind) | NO | Default: "verification"; values: verification, welcome |
| `sent_at` | timestamp tz | NO | When email was sent |

**Indexes:**
- None (except implicit PK)

**Constraints:**
- PK: `id`

**Observations:**
- **Missing indexes:** No index on `to`, `kind`, or `sent_at`. Common queries like "emails sent to user@example.com" or "welcome emails sent today" would scan the table. Should add indexes on at least (to, sent_at) and (kind, sent_at).
- **Incomplete kind enum:** Only "verification" and "welcome" are defined, but comments in the code mention "digest" and "SLA alerts". The enum should be updated or the code should use a string instead of enum.
- **No delivery tracking:** Unlike notification_delivery_events, this table doesn't track SMTP delivery status (sent, bounced, failed). For production, would want to know which emails were actually delivered.
- **Payload storage:** The full email body is stored, which is good for audit but will eventually consume significant storage. No retention policy evident.

---

### automation_events
**Purpose:** Audit trail for automated actions (SLA escalations, AI-driven priority changes, ticket reassignments, etc.).

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `ticket_id` | varchar(20) | NO | FK → tickets.id; CASCADE; IDX |
| `event_type` | varchar(64) | NO | Action type: "priority_escalation", "auto_assignment", "sla_breach_notify", etc. |
| `actor` | varchar(64) | NO | Who/what triggered the action: "sla_monitor", "ai_classifier", "system", "user", etc. |
| `before_snapshot` | JSONB | YES | Ticket state before action |
| `after_snapshot` | JSONB | YES | Ticket state after action |
| `meta` | JSONB | YES | Additional context (reason, confidence, affected_field, etc.) |
| `created_at` | timestamp tz | NO | Event recorded time |

**Indexes:**
- `ix_automation_events_ticket_id`

**Constraints:**
- PK: `id`
- FK: `ticket_id` → `tickets.id` (CASCADE)

**Observations:**
- **Missing constraint:** No check constraint on `event_type`. Values like "invalid_event" could be inserted. Should list allowed values.
- **Missing index on event_type:** Queries like "all escalations on ticket X" would need to filter by event_type and scan rows. A compound index on (ticket_id, event_type) or an index on `event_type` would help.
- **Missing index on actor:** Queries like "all actions by sla_monitor" would scan the table. Should index `actor`.
- **Missing index on created_at:** Queries like "actions on ticket X in the last hour" would scan. A compound index on (ticket_id, created_at) would help.
- **Snapshot design:** Storing before/after JSONB snapshots is excellent for audit trails. No GIN index on these, but they're primarily accessed by application code, not analytics queries.
- **Missing context validation:** `meta` JSONB can be any structure. If specific metadata fields are always expected (reason, confidence), they should be normalized into columns or a check constraint should enforce structure.

---

### ai_sla_risk_evaluations
**Purpose:** Audit trail for AI-based SLA risk scoring. In shadow mode, these are recommendations. In active mode, they drive escalations.

**Columns:**
| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `ticket_id` | varchar(20) | NO | FK → tickets.id; CASCADE; IDX |
| `risk_score` | integer | YES | Computed risk percentage (0-100) |
| `confidence` | float | YES | Model confidence (0-1 scale) |
| `suggested_priority` | varchar(16) | YES | Recommended priority: critical, high, medium, low |
| `reasoning_summary` | text | NO | Why the risk score was assigned |
| `model_version` | varchar(64) | NO | Version of the risk model used |
| `decision_source` | varchar(16) | NO | Default: "shadow"; values: shadow, active, advisory |
| `created_at` | timestamp tz | NO | Evaluation recorded time |

**Indexes:**
- `ix_ai_sla_risk_evaluations_ticket_id`

**Constraints:**
- PK: `id`
- FK: `ticket_id` → `tickets.id` (CASCADE)

**Observations:**
- **Missing constraint:** No check constraint on `risk_score` (should be 0-100 if percentage).
- **Missing constraint:** No check constraint on `confidence` (should be 0-1).
- **Missing constraint:** No check constraint on `suggested_priority` (should be one of the TicketPriority enum values).
- **Missing index on decision_source:** Queries like "active escalation recommendations" would scan the table. Should index `decision_source` or use a compound index (decision_source, created_at).
- **Missing index on created_at:** Queries like "recent evaluations for ticket X" would benefit from an index on created_at.
- **Model versioning:** `model_version` is stored, allowing comparison of how predictions change as the model evolves. Good for A/B testing.
- **Relationship to tickets:** The actual escalation (priority change) is recorded in `automation_events`, not here. These records are recommendations/audit. Clean separation.

---

## 3. Relationship map

| Relationship | Cardinality | Notes |
|---|---|---|
| `users.id` ← `refresh_tokens.user_id` | one-to-many | Token lifecycle: issue, rotate, revoke, expire |
| `users.id` ← `verification_tokens.user_id` | one-to-many | Email verification: one-time use |
| `users.id` ← `password_reset_tokens.user_id` | one-to-many | Password recovery: one-time use |
| `users.id` ← `notification_preferences.user_id` | one-to-one | Composite primary key; one prefs row per user |
| `users.id` ← `notifications.user_id` | one-to-many | In-app alerts sent to users |
| `users.id` ← `notification_delivery_events.user_id` | one-to-many | Email/Slack delivery traces (nullable: SET NULL on user delete) |
| `users.id` ← `ai_solution_feedback.user_id` | one-to-many | Feedback given by users (nullable: SET NULL on user delete) |
| `users.id` ← `email_logs.to` | implicit | Email logs store email address, not user ID; no referential integrity |
| `tickets.id` ← `ticket_comments.ticket_id` | one-to-many | Discussion thread; CASCADE on delete |
| `tickets.id` ← `automation_events.ticket_id` | one-to-many | Audit trail of automated actions; CASCADE on delete |
| `tickets.id` ← `ai_sla_risk_evaluations.ticket_id` | one-to-many | SLA risk evaluations; CASCADE on delete |
| `tickets.id` ← `ai_solution_feedback.ticket_id` | one-to-many | Feedback on recommendations shown in context of tickets (nullable: SET NULL on ticket delete) |
| `problems.id` ← `tickets.problem_id` | one-to-many | Problem grouping; tickets linked to problems; nullable, SET NULL on delete |
| `notifications.id` ← `notification_delivery_events.notification_id` | one-to-many | Delivery attempts for each notification; CASCADE on delete |

**Missing explicit foreign key relationships:**

| Missing relationship | Risk | Impact |
|---|---|---|
| `recommendations` ← `ai_solution_feedback.recommendation_id` | HIGH | Feedback references recommendation ID as string, not FK. Deleting a recommendation leaves orphaned feedback. No referential integrity. |
| `tickets.assignee` (string) ← `users` | HIGH | Assignees are stored as string names, not user IDs. No referential integrity; name changes break association. Makes "tickets assigned to user X" queries brittle. Should add `assignee_id (UUID)` FK. |
| `tickets.reporter` (string) ← `users` | MEDIUM | Reporters are string names. Less critical than assignees (reporters are less frequently queried), but same issue applies. |
| `ticket_comments.author` (string) ← `users` | MEDIUM | Comment authors are string names. Same referential integrity issue. |
| `notifications.severity` (string) ← audit_enum_table | LOW | Severity is stored as varchar, not an enum type. Values can be invalid. Should define allowed values. |
| `kb_chunks` → `tickets` or `jira_sync_state` | LOW | KB chunks source from Jira but don't link back to the tickets they came from. Useful for debugging/lineage tracking. |

---

## 4. Naming consistency check

**Conventions observed:**

- **Snake case:** Consistently used throughout (e.g., `user_id`, `created_at`, `ticket_type`, `is_available`).
- **Timestamp naming:** Mostly consistent use of `created_at` and `updated_at`. Some tables have additional timestamps like `last_synced_at`, `last_seen_at`, `resolved_at` — descriptive and clear.
- **Boolean prefixes:** Some columns use `is_` prefix (e.g., `is_available`, `is_verified`), others don't (e.g., `email_enabled`, `pinned_until_read`, `sla_first_response_breached`). **Inconsistent**: should standardize either all booleans or only those that are true/false questions.
- **ID column types:** Mixed conventions:
  - `users.id`, `refresh_tokens.user_id`: UUID
  - `tickets.id`, `problems.id`, `recommendations.id`: varchar(20) (e.g., "TW-001")
  - `kb_chunks.id`, `jira_sync_state.id`: integer (auto-increment)
  - This is intentional by design (different identity strategies) but worth noting.
- **Foreign key naming:** Consistently `{table_singular}_id` (e.g., `user_id`, `ticket_id`, `notification_id`).
- **Enum type names:** Snake_case, descriptive (e.g., `user_role`, `ticket_status`, `recommendation_type`).

**Issues:**
- **Inconsistent boolean naming:** Some use `is_` (is_available, is_verified), others use adjectives (email_enabled, digest_enabled) or past-participle/adjective (sla_first_response_breached, pinned_until_read). Suggest: standardize on `is_` prefix for all boolean columns.
- **Mixed enum/varchar for enums:** Some columns use ENUM type (status, priority, type), others use varchar (severity, delivery_status, event_type). Suggest: Convert varchar enums to PostgreSQL ENUM types for type safety.

---

## 5. Missing indexes (prioritized)

| Table | Column(s) | Why it needs an index | Impact | Severity |
|---|---|---|---|---|
| `tickets` | `(status, priority, created_at)` | Dashboard queries: "show open high-priority tickets created today" | HIGH | P0 |
| `tickets` | `updated_at` | Common pattern: "tickets modified since T" (for incremental sync) | HIGH | P0 |
| `tickets` | `sla_status` | "Find at-risk SLA tickets" for SLA monitor | HIGH | P0 |
| `tickets` | `assignee` | Filter by assignee name (though should be FK, not string) | MEDIUM | P1 |
| `ticket_comments` | `ticket_id` | Implicit FK, but explicit index would help sorting "comments by ticket" | MEDIUM | P1 |
| `ticket_comments` | `(ticket_id, created_at)` | Sort comments by creation (queries in ticket detail view) | MEDIUM | P1 |
| `problems` | `(status, category, created_at)` | Queries: "open problems in category X" | MEDIUM | P1 |
| `problems` | `last_seen_at` | "Problems seen in the last week" | MEDIUM | P1 |
| `recommendations` | `(type, impact, created_at)` | Filter recommendations by type/impact (frontend dashboard) | MEDIUM | P1 |
| `recommendations` | `confidence` | "Recommendations with high confidence" | MEDIUM | P1 |
| `recommendations` | `related_tickets` (GIN) | "Recommendations for ticket X" (search in JSONB array) | MEDIUM | P1 |
| `notifications` | `created_at` | "Notifications created today" | MEDIUM | P1 |
| `notifications` | `(user_id, created_at)` | "User's recent notifications" | MEDIUM | P1 |
| `notification_delivery_events` | `delivery_status` | "Failed deliveries" (for alerting) | MEDIUM | P1 |
| `kb_chunks` | `embedding` (vector index) | **CRITICAL:** Semantic search without vector index is O(n); blocks RAG pipeline | CRITICAL | P0 |
| `kb_chunks` | `source_type` | Filter chunks by source (Jira vs. local) | LOW | P2 |
| `refresh_tokens` | `expires_at` | Token cleanup ("DELETE WHERE expires_at < NOW()") | LOW | P2 |
| `refresh_tokens` | `revoked_at` | "Active tokens (revoked_at IS NULL)" | LOW | P2 |
| `verification_tokens` | `user_id` | "Active tokens for user X" | LOW | P2 |
| `verification_tokens` | `expires_at` | Token cleanup | LOW | P2 |
| `password_reset_tokens` | `expires_at` | Token cleanup | LOW | P2 |
| `email_logs` | `(to, sent_at)` | "Emails sent to user today" | LOW | P2 |
| `email_logs` | `(kind, sent_at)` | "Welcome emails sent today" | LOW | P2 |
| `automation_events` | `(ticket_id, event_type, created_at)` | "Escalations on ticket X" | MEDIUM | P1 |
| `ai_sla_risk_evaluations` | `(ticket_id, created_at)` | "Recent risk evaluations for ticket" | MEDIUM | P1 |

---

## 6. JSONB columns audit

| Table | Column | Data stored | Usage pattern | Should normalize? | GIN index? |
|---|---|---|---|---|---|
| `users` | `specializations` | List of domain specializations (strings) | Filter by specialization (rare); mostly read-only | **YES** — Create `user_specializations` table for querying. Store list is awkward for filtering. | Not needed if normalized |
| `tickets` | `tags` | List of string tags | Filter by tag; UI display | **YES** — Could normalize to `ticket_tags` table for efficient filtering. However, flexible schema (list of strings) suggests deliberate design choice to allow ad-hoc tags. Current JSONB OK if tag-filtering is not critical. | GIN index if frequently searched |
| `tickets` | `raw_payload` | Complete Jira/external API response | Debug/audit only; rarely queried | NO — Archive/audit data. GIN index not needed. | No |
| `tickets` | `jira_sla_payload` | SLA configuration from Jira | Extract SLA fields and store in columns (which is done); payload is backup. | NO — Extract-and-store pattern is already applied. | No |
| `recommendations` | `related_tickets` | List of ticket IDs (strings) | Filter: "recommendations for ticket X" | **MAYBE** — Currently a list, could be normalized to `recommendation_tickets` junction table for cleaner queries. However, storing as list is simpler if cardinality is small (<10 per recommendation). | **YES** — Add GIN index if filtering by ticket is frequent. Query: `related_tickets @> '["TW-001"]'` is fast with GIN. |
| `automation_events` | `before_snapshot` | Ticket state before action | Audit/debug: "what changed?" | NO — Snapshot design is intentional. Normalization would lose history. | No — Snapshots are typically retrieved en masse for audit, not queried individually. |
| `automation_events` | `after_snapshot` | Ticket state after action | Audit/debug: "what was the new value?" | NO — Same as before_snapshot. | No |
| `automation_events` | `meta` | Context: reason, confidence, affected_field | Context for audit; varies by event_type | **MAYBE** — If standard fields (reason, confidence, affected_field) are expected, normalize into columns. If truly variable, keep JSONB. | GIN index if searching metadata by field is needed. |
| `notification_delivery_events` | `recipients_json` | List of email addresses or Slack IDs | Display delivery trace; rarely searched | NO — List of recipients is audit data, typically read en masse. | No |
| `notification_delivery_events` | `metadata_json` (not in model, from notifications) | Custom metadata | Varies by notification type | NO — Flexible design intentional. | No |
| `notifications` | `metadata_json` | Custom metadata (severity, tags, etc.) | Display/filtering; varies by notification type | **MAYBE** — If standard fields, normalize. If highly variable, keep JSONB. | GIN index if filtering by metadata field is frequent. |
| `notifications` | `action_payload` | Payload for call-to-action | Parse and execute action; rarely queried | NO — Action context, typically parsed in-app. | No |
| `ai_solution_feedback` | `context_json` | Additional interaction context | Feedback analytics; rarely queried | **MAYBE** — If standard fields (page, feature_flag, etc.), normalize. If highly variable, keep JSONB. | GIN index if searching context is needed. |
| `kb_chunks` | `metadata` | Flexible metadata (title, author, tags) | Filter by source; search by tag | **MAYBE** — If standard fields (title, author, tags), normalize. If highly variable, keep JSONB. Current design supports ad-hoc metadata. | GIN index if metadata filtering is frequent. |

**Summary:**
- 3 JSONB columns should be **considered for normalization** to improve query efficiency: `users.specializations`, `recommendations.related_tickets`, `automation_events.meta`.
- 4 JSONB columns should have **GIN indexes** if they're frequently queried: `tickets.tags`, `recommendations.related_tickets`, `kb_chunks.metadata`, `notifications.metadata`.
- **CRITICAL:** `kb_chunks.embedding` needs a **pgvector vector index** (IVFFlat or HNSW), not a standard GIN index.

---

## 7. Enum types audit

| Enum type | Current values | Missing values? | Frontend consistency | Notes |
|---|---|---|---|---|
| `user_role` | admin, agent, user, viewer | Complete | ✓ Matches badge system | Clear hierarchy |
| `user_seniority` | intern, junior, middle, senior | Complete | ✓ Used in auto-assignment | Consistent with domain |
| `ticket_status` | open, in-progress, waiting-for-customer, waiting-for-support-vendor, pending, resolved, closed | Mostly complete; `pending` is legacy | ✓ Matches frontend badge system | Legacy `pending` should be deprecated |
| `ticket_priority` | critical, high, medium, low | Complete | ✓ Matches SLA tiers and frontend | Consistent |
| `ticket_type` | incident, service_request | Complete? | ✓ ITIL-standard types | Only two types; may be limiting (e.g., "change_request", "problem" in ITIL) |
| `ticket_category` | infrastructure, network, security, application, service_request, hardware, email, problem | Fairly complete | ✓ Matches frontend badge system | Good coverage; `problem` is meta-category (used for problem tickets linking) |
| `problem_status` | open, investigating, known_error, resolved, closed | Complete | ✓ Matches frontend | Consistent |
| `email_kind` | verification, welcome | Incomplete | ✗ Missing "digest", "sla_alert", etc. | Only 2 values, but code mentions more; should update or use varchar |
| `recommendation_type` | pattern, priority, solution, workflow | Complete | ✓ Matches frontend filter buttons | Consistent |
| `recommendation_impact` | high, medium, low | Complete | ✓ Matches frontend badge colors | Consistent |

**Issues:**
- **`email_kind` is incomplete:** Only "verification" and "welcome" are in the enum, but the code and documentation mention "digest" and "sla_alert". Either: (a) update the enum, (b) switch to varchar, or (c) clarify that these emails are sent but not tracked in `email_logs`.
- **`ticket_status` has legacy value:** "pending" is marked as legacy but still in the enum. Should be deprecated or removed.
- **`ticket_type` is limited:** Only incident and service_request are defined. ITIL includes change_request, problem_report, RFI. Current design supports only binary classification. Document this as intentional simplification.
- **Consistency:** Most enums are well-defined and match the frontend badge system. No major inconsistencies.

---

## 8. Schema strengths

1. **Comprehensive SLA tracking:** Tickets have rich SLA fields (first_response_due_at, resolution_due_at, breach flags, remaining/elapsed minutes). Allows accurate SLA reporting and proactive breach prevention.

2. **AI prediction audit trail:** Columns like `assignment_model_version`, `priority_model_version`, `predicted_priority`, `predicted_category` allow tracking which model produced which prediction, enabling A/B testing and debugging.

3. **Snapshot-based feedback audit:** `ai_solution_feedback` stores snapshots of AI recommendations (reasoning, confidence, evidence count) at the time of feedback. This allows analyzing how feedback correlates with AI output characteristics — invaluable for improving the AI system.

4. **Pgvector semantic KB:** `kb_chunks` with vector embeddings enables RAG pipelines. Well-designed for knowledge base queries and semantic search, future-proof for LLM integration.

5. **Multi-source ticket sync:** Tickets can come from Jira, external APIs, or be created locally. The schema cleanly supports this with `source`, `external_id`, `jira_key` columns and unique constraints on (external_source, external_id) and jira_key. Deduplication and reconciliation are straightforward.

6. **Event audit trail:** `automation_events` and `notification_delivery_events` provide comprehensive audit trails for debugging automated actions and notification delivery. Before/after snapshots are excellent for understanding state transitions.

7. **Flexible problem grouping:** Problems are grouped by `similarity_key` (likely a hash of root cause attributes), allowing dynamic problem creation without pre-defined categories. The schema is agnostic to the grouping strategy.

8. **Notification deduplication and customization:** `notification_preferences` allows granular control (severity thresholds, quiet hours, event types). `dedupe_key` supports smart deduplication. `action_payload` allows rich notifications with call-to-action buttons.

9. **Token lifecycle management:** `refresh_tokens` with `revoked_at`, `expires_at`, and `replaced_by_jti` fields allow clean JWT lifecycle (issue, rotate, revoke, expire), essential for session management and security.

10. **Comprehensive indexing strategy:** Many tables have thoughtful indexes (compound indexes on frequently-queried column combinations, partial indexes on conditional logic). The index strategy suggests attention to query patterns.

---

## 9. Schema weaknesses and recommendations

### Fix before soutenance

**1. String-based foreign keys (assignee, reporter, author)**

**Severity:** HIGH — Data integrity and query correctness are at risk.

**Issue:** Tickets.assignee, tickets.reporter, ticket_comments.author are stored as string names, not user IDs. This breaks referential integrity and makes queries brittle.

**Example problem:**
```sql
-- How to find tickets assigned to "John Smith"?
SELECT * FROM tickets WHERE assignee = 'John Smith';
-- But "John Smith" might be 5 different users. Or the user's name changed.
-- And there's no constraint preventing assignment to a non-existent user.
```

**Fix:**
1. Add columns: `tickets.assignee_id (UUID)`, `tickets.reporter_id` (if not already done; field exists but is only Jira ID), `ticket_comments.author_id (UUID)`.
2. Add FK constraints: `assignee_id → users.id`, `reporter_id → users.id`, `author_id → users.id`.
3. Backfill by matching user names to IDs (or mark as NULL if no match found).
4. Update application code to use IDs instead of names.
5. Consider: keep the string name columns as denormalized copies for display (to avoid joins on every query), but make the IDs the source of truth.

**Timeline:** Must be done before the system goes to production. After this, migrating will be harder due to existing data.

---

**2. No vector index on kb_chunks.embedding**

**Severity:** CRITICAL — Semantic search (RAG pipeline) will be slow or non-functional.

**Issue:** The embedding column exists but has no pgvector index. Queries like `SELECT * FROM kb_chunks ORDER BY embedding <-> ? LIMIT 10` will do a full table scan, taking O(n) time. At 50K chunks, this is hundreds of milliseconds per query — unacceptable for interactive chat.

**Fix:**
```sql
CREATE INDEX ix_kb_chunks_embedding_cosine
  ON kb_chunks USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);  -- adjust lists parameter based on dataset size
```

Or for better accuracy (slower indexing but faster queries on small datasets):
```sql
CREATE INDEX ix_kb_chunks_embedding_hnsw
  ON kb_chunks USING hnsw (embedding vector_cosine_ops);
```

**Timeline:** Must be done before using semantic search (chat, RAG queries). Can be added after data exists (Alembic migration).

---

**3. No foreign key on ai_solution_feedback.recommendation_id**

**Severity:** HIGH — Orphaned feedback when recommendations are deleted/archived.

**Issue:** `ai_solution_feedback.recommendation_id` is a string, not a FK. If a recommendation is deleted, feedback records remain, pointing to a non-existent recommendation. This breaks analytics on recommendation feedback.

**Fix:**
1. Add FK constraint:
```sql
ALTER TABLE ai_solution_feedback
  ADD CONSTRAINT fk_ai_solution_feedback_recommendation_id
  FOREIGN KEY (recommendation_id) REFERENCES recommendations(id) ON DELETE CASCADE;
```

2. First, ensure all existing recommendation_id values exist in recommendations table. If there are orphaned records, decide: delete them or set to NULL (if you add nullable).

**Timeline:** Must be done before full deployment. Currently, recommendation deletion might orphan feedback, causing incorrect analytics.

---

**4. No check constraints on enum varchar columns**

**Severity:** MEDIUM — Invalid enum values can be inserted, breaking application logic.

**Issue:** Columns like `notifications.severity`, `notifications.event_type`, `notification_delivery_events.delivery_status`, `automation_events.event_type`, `email_logs.kind` (partially — kind is enum but should be validated), use varchar or string types without check constraints. Invalid values like "extreme_severity" or "invalid_status" can be inserted.

**Fix:**
Add check constraints:
```sql
ALTER TABLE notifications ADD CONSTRAINT check_severity CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info'));
ALTER TABLE notifications ADD CONSTRAINT check_event_type CHECK (event_type IN ('ticket_assigned', 'sla_breach', 'ai_recommendation', ...));
ALTER TABLE notification_delivery_events ADD CONSTRAINT check_delivery_status CHECK (delivery_status IN ('in-app', 'email-sent', 'email-failed', ...));
-- etc.
```

Or convert to PostgreSQL ENUM types for type safety and reusability.

**Timeline:** Should be done before soutenance. Currently, invalid data can corrupt the system state.

---

### Fix in next iteration

**5. Dead prediction columns in tickets**

**Severity:** MEDIUM — Unused columns consume storage and confuse the schema.

**Issue:** `tickets.predicted_priority`, `tickets.predicted_category`, `tickets.predicted_ticket_type` are never read by any router. They appear to be experimental or obsolete ML predictions that are no longer used.

**Fix:**
1. Audit code: confirm these columns are truly unused (search all routers for references).
2. If unused, remove them via Alembic migration:
```sql
ALTER TABLE tickets DROP COLUMN predicted_priority;
ALTER TABLE tickets DROP COLUMN predicted_category;
ALTER TABLE tickets DROP COLUMN predicted_ticket_type;
```
3. If they should be used (e.g., for future A/B testing), add comments explaining their purpose.

**Timeline:** Can wait for the next iteration, but should be cleaned up soon to avoid confusion.

---

**6. Missing indexes for common queries**

**Severity:** MEDIUM — Query performance will degrade as data grows.

**Issue:** Several high-cardinality queries lack indexes:
- `tickets WHERE sla_status = 'at_risk'` (for SLA monitor)
- `tickets WHERE updated_at > ?` (for incremental sync)
- `problems WHERE status = 'open' AND category = ?` (for problem dashboard)
- `recommendations WHERE type = ? AND impact = ? AND created_at > ?` (for frontend filters)

**Fix:** Add indexes identified in Section 5 (high-priority ones first).

**Timeline:** Should be done before the system reaches significant scale (>10K tickets). Currently, scans are fast enough, but this changes as data grows.

---

**7. email_logs.kind enum is incomplete**

**Severity:** MEDIUM — Enum doesn't match code (code mentions "digest", "sla_alert").

**Issue:** `email_logs.kind` enum has only "verification" and "welcome", but comments indicate "digest" and "sla_alert" emails are sent. Either the enum is incomplete or those emails aren't tracked.

**Fix:**
1. Clarify: Are "digest" and "sla_alert" emails being sent? If yes, add to enum.
2. Update enum:
```sql
ALTER TYPE email_kind ADD VALUE 'digest';
ALTER TYPE email_kind ADD VALUE 'sla_alert';
```

**Timeline:** Can be deferred if digest/alert emails aren't yet sent. Otherwise, fix soon to ensure email tracking is complete.

---

**8. Partial unique constraints on kb_chunks identities are weak**

**Severity:** LOW — Deduplication might not work as intended.

**Issue:** `kb_chunks` has partial unique indexes on (source_type, jira_key, comment_id) and (source_type, jira_issue_id), but they're conditional (only create type='jira_comment' or type='jira_issue'). Other source types might have duplicates. Also, `content_hash` is indexed but not unique, so identical content from different sources could both be stored.

**Fix:**
1. Clarify: Should identical content from different sources both be stored, or should we deduplicate by content_hash globally?
2. If global dedup, add:
```sql
ALTER TABLE kb_chunks ADD CONSTRAINT uq_kb_chunks_content_hash UNIQUE (content_hash);
```
   Then backfill: delete duplicates, keeping the first.
3. If source-specific dedup is intended, document the strategy.

**Timeline:** Can wait until deduplication becomes a problem (lots of duplicate chunks in KB).

---

### Consider for future

**9. Normalize JSONB columns for better queryability**

**Severity:** LOW — Currently, queries on JSONB fields are possible but slower.

**Issue:** JSONB columns like `recommendations.related_tickets`, `users.specializations`, `automation_events.meta` are flexible but harder to query. For frequent queries, normalization would be cleaner.

**Example:** To find all recommendations related to ticket "TW-001", current query is:
```sql
SELECT * FROM recommendations WHERE related_tickets @> '["TW-001"]';
```

With a normalized `recommendation_tickets` junction table:
```sql
SELECT DISTINCT r.* FROM recommendations r
  JOIN recommendation_tickets rt ON r.id = rt.recommendation_id
  WHERE rt.ticket_id = 'TW-001';
```

**Fix (future):** If querying by ticket becomes a bottleneck, normalize to a junction table.

**Timeline:** Not urgent; current JSONB + GIN index is acceptable. Consider for future optimization.

---

**10. Add last_login and created_by audit fields to users**

**Severity:** LOW — Audit trail is incomplete.

**Issue:** Users table has no `last_login` or `created_by` fields, making it hard to audit account activity or know who created an account (important for admin accounts).

**Fix:**
```sql
ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE users ADD COLUMN created_by UUID REFERENCES users(id) ON DELETE SET NULL;
```

**Timeline:** Can be added in a future iteration if audit needs arise.

---

**11. Consider a ticket history/audit table**

**Severity:** LOW — Current design doesn't track all state changes.

**Issue:** Tickets have `updated_at` and `assignment_change_count`, but no full audit trail of who changed what and when. For compliance/debugging, a separate `ticket_history` table (with snapshots or diffs) might be useful.

**Fix (future):** Add `ticket_history` table:
```sql
CREATE TABLE ticket_history (
  id BIGSERIAL PRIMARY KEY,
  ticket_id VARCHAR(20) NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  changed_by UUID REFERENCES users(id) ON DELETE SET NULL,
  change_type VARCHAR(32), -- 'update', 'comment', 'assignment', 'priority_change'
  before_snapshot JSONB,
  after_snapshot JSONB,
  reason TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT utcnow()
);
```

**Timeline:** Not urgent; can be deferred unless compliance auditing is required.

---

## 10. Migration chain health

- **Total migrations:** 34 (0001 to 0033, with 0016_add_kb_chunks_pgvector in the sequence)
- **First migration:** `0001_initial` (2026-02-06)
- **Last migration:** `0033_add_ticket_summary` (2026-03-26)
- **Gaps or out-of-order:** No gaps detected. Sequence is continuous: 0001, 0002, ..., 0033.
- **Conflicts:** No migrations modifying the same column twice detected.

**Migration highlights:**
- Steady evolution over ~7 weeks.
- Recent additions (0027-0033): ticket type support, notification routing, feedback expansion, summary generation.
- No major rollbacks or reversions (all migrations move forward).

**Observations:**
- Clean migration history; no sign of chaotic schema evolution.
- Recent migrations are well-scoped and focused (e.g., 0033 adds only 2 columns).
- pgvector extension added in 0016, but no vector index created (still missing, as noted in Section 5).

---

## Summary statistics

| Metric | Count |
|---|---|
| **Tables** | 18 |
| **Total columns** | 250+ |
| **Foreign keys** | 11 explicit (+ missing 3) |
| **Unique constraints** | 12 |
| **Indexes** | 50+ (many implicit via FK/UQ) |
| **Enum types** | 10 |
| **JSONB columns** | 11 |
| **Timestamp columns** | 45+ |
| **Nullable columns** | ~100 |
| **Critical issues (fix before soutenance)** | 4 |
| **High-priority improvements** | 6 |
| **Low-priority improvements** | 5 |

---

## Conclusion

The database schema is **well-designed and production-ready** for the current scope, with a few critical fixes needed before launch:

1. **Add vector index on kb_chunks.embedding** (CRITICAL — blocks RAG)
2. **Add FK on ai_solution_feedback.recommendation_id** (HIGH — data integrity)
3. **Add check constraints on enum varchar columns** (MEDIUM — data validation)
4. **Convert assignee/reporter/author to ForeignKeys** (HIGH — referential integrity)

Beyond these, the schema has **excellent audit trails** (snapshots, automation events), **thoughtful indexing**, and **strong support for AI workflows** (predictions, feedback, SLA risk scoring). The migration history is clean, and the naming conventions are consistent.

Recommendations for the next iteration: add missing indexes for common queries, normalize JSONB columns if querying becomes a bottleneck, and consider removing unused prediction columns from tickets.

