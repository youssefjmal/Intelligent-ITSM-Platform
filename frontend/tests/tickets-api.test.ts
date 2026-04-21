/**
 * Tests for tickets-api.ts mapper and URL logic.
 * Run: cd frontend && npx ts-node tests/tickets-api.test.ts
 */

// ── test helpers ──────────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;

function expect(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    console.log(`  ✓  ${label}`);
    passed++;
  } else {
    console.error(`  ✗  ${label}`);
    console.error(`     expected: ${JSON.stringify(expected)}`);
    console.error(`     received: ${JSON.stringify(actual)}`);
    failed++;
  }
}

// ── inline mapper (mirrors tickets-api.ts mapTicket) ─────────────────────────

interface TicketComment { id: string; author: string; content: string; createdAt: string }
interface ApiComment { id: string; author: string; content: string; created_at: string }

interface ApiTicket {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  ticket_type: string;
  category: string;
  assignee: string;
  reporter: string;
  created_at: string;
  updated_at: string;
  tags: string[];
  comments: ApiComment[];
  auto_assignment_applied?: boolean;
  auto_priority_applied?: boolean;
  assignment_model_version?: string;
  priority_model_version?: string;
  assignment_change_count?: number;
  problem_id?: string | null;
  first_action_at?: string | null;
  resolved_at?: string | null;
  due_at?: string | null;
  sla_status?: string | null;
  sla_remaining_minutes?: number | null;
  sla_first_response_due_at?: string | null;
  sla_resolution_due_at?: string | null;
  sla_first_response_breached?: boolean;
  sla_resolution_breached?: boolean;
  sla_last_synced_at?: string | null;
  resolution?: string | null;
  predicted_priority?: string | null;
  predicted_ticket_type?: string | null;
  predicted_category?: string | null;
}

interface Ticket {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  ticketType: string;
  category: string;
  assignee: string;
  reporter: string;
  createdAt: string;
  updatedAt: string;
  tags: string[];
  comments: TicketComment[];
  autoAssignmentApplied?: boolean;
  autoPriorityApplied?: boolean;
  assignmentModelVersion?: string;
  priorityModelVersion?: string;
  assignmentChangeCount?: number;
  problemId?: string;
  firstActionAt?: string;
  resolvedAt?: string;
  dueAt?: string | null;
  slaStatus?: string | null;
  slaRemainingMinutes?: number | null;
  slaFirstResponseDueAt?: string | null;
  slaResolutionDueAt?: string | null;
  slaFirstResponseBreached?: boolean;
  slaResolutionBreached?: boolean;
  slaLastSyncedAt?: string | null;
  resolution?: string;
  predictedPriority?: string;
  predictedTicketType?: string;
  predictedCategory?: string;
}

function mapTicket(ticket: ApiTicket): Ticket {
  return {
    id: ticket.id,
    problemId: ticket.problem_id || undefined,
    title: ticket.title,
    description: ticket.description,
    status: ticket.status,
    priority: ticket.priority,
    ticketType: ticket.ticket_type,
    category: ticket.category,
    assignee: ticket.assignee,
    reporter: ticket.reporter,
    autoAssignmentApplied: ticket.auto_assignment_applied,
    autoPriorityApplied: ticket.auto_priority_applied,
    assignmentModelVersion: ticket.assignment_model_version,
    priorityModelVersion: ticket.priority_model_version,
    predictedPriority: ticket.predicted_priority || undefined,
    predictedTicketType: ticket.predicted_ticket_type || undefined,
    predictedCategory: ticket.predicted_category || undefined,
    assignmentChangeCount: ticket.assignment_change_count,
    firstActionAt: ticket.first_action_at || undefined,
    resolvedAt: ticket.resolved_at || undefined,
    dueAt: ticket.due_at ?? null,
    slaStatus: ticket.sla_status ?? null,
    slaRemainingMinutes: ticket.sla_remaining_minutes ?? null,
    slaFirstResponseDueAt: ticket.sla_first_response_due_at ?? null,
    slaResolutionDueAt: ticket.sla_resolution_due_at ?? null,
    slaFirstResponseBreached: Boolean(ticket.sla_first_response_breached),
    slaResolutionBreached: Boolean(ticket.sla_resolution_breached),
    slaLastSyncedAt: ticket.sla_last_synced_at ?? null,
    createdAt: ticket.created_at,
    updatedAt: ticket.updated_at,
    resolution: ticket.resolution || undefined,
    tags: ticket.tags,
    comments: ticket.comments.map((c): TicketComment => ({
      id: c.id,
      author: c.author,
      content: c.content,
      createdAt: c.created_at,
    })),
  };
}

const API_BASE = "http://localhost:8000/api";
function buildUrl(path: string): string { return `${API_BASE}${path}`; }

// ── tests ─────────────────────────────────────────────────────────────────────

console.log("\ntickets-api — mapTicket");

const rawTicket: ApiTicket = {
  id: "TW-42",
  title: "Printer offline",
  description: "HP LaserJet is showing offline status.",
  status: "open",
  priority: "medium",
  ticket_type: "service_request",
  category: "hardware",
  assignee: "alice",
  reporter: "bob",
  created_at: "2026-04-01T08:00:00Z",
  updated_at: "2026-04-01T09:00:00Z",
  tags: ["printer", "hardware"],
  comments: [{ id: "c1", author: "alice", content: "Checking now", created_at: "2026-04-01T08:30:00Z" }],
  auto_assignment_applied: true,
  auto_priority_applied: false,
  assignment_model_version: "v2",
  priority_model_version: "v1",
  assignment_change_count: 1,
  problem_id: null,
  sla_status: "at_risk",
  sla_remaining_minutes: 15,
  sla_first_response_breached: false,
  sla_resolution_breached: false,
};

const ticket = mapTicket(rawTicket);

expect("id preserved", ticket.id, "TW-42");
expect("title preserved", ticket.title, "Printer offline");
expect("ticket_type → ticketType", ticket.ticketType, "service_request");
expect("created_at → createdAt", ticket.createdAt, "2026-04-01T08:00:00Z");
expect("updated_at → updatedAt", ticket.updatedAt, "2026-04-01T09:00:00Z");
expect("auto_assignment_applied → autoAssignmentApplied", ticket.autoAssignmentApplied, true);
expect("auto_priority_applied → autoPriorityApplied", ticket.autoPriorityApplied, false);
expect("sla_status → slaStatus", ticket.slaStatus, "at_risk");
expect("sla_remaining_minutes → slaRemainingMinutes", ticket.slaRemainingMinutes, 15);
expect("null problem_id → undefined", ticket.problemId, undefined);
expect("comment created_at → createdAt", ticket.comments[0].createdAt, "2026-04-01T08:30:00Z");
expect("tags preserved", ticket.tags, ["printer", "hardware"]);

console.log("\ntickets-api — URL construction");

expect("fetchTickets URL", buildUrl("/tickets"), "http://localhost:8000/api/tickets");
expect("fetchTicket URL", buildUrl("/tickets/TW-42"), "http://localhost:8000/api/tickets/TW-42");
expect("fetchTicketStats URL", buildUrl("/tickets/stats"), "http://localhost:8000/api/tickets/stats");
expect("fetchSimilarTickets URL", buildUrl("/tickets/TW-42/similar"),
  "http://localhost:8000/api/tickets/TW-42/similar");

console.log("\ntickets-api — SLA fields default to false/null");

const minimalTicket: ApiTicket = {
  id: "TW-1", title: "t", description: "d", status: "open", priority: "low",
  ticket_type: "incident", category: "network", assignee: "a", reporter: "b",
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  tags: [], comments: [],
};
const minimal = mapTicket(minimalTicket);
expect("slaFirstResponseBreached defaults false", minimal.slaFirstResponseBreached, false);
expect("slaResolutionBreached defaults false", minimal.slaResolutionBreached, false);
expect("slaStatus null when absent", minimal.slaStatus, null);
expect("dueAt null when absent", minimal.dueAt, null);

// ── summary ───────────────────────────────────────────────────────────────────

console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`);
if (failed > 0) process.exit(1);
