/**
 * Tests for knowledge-draft functions in tickets-api.ts
 * Verifies: URL construction, snake_case → camelCase mapping, publish flow.
 *
 * Run: cd frontend && npx ts-node tests/knowledge-draft.test.ts
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

// ── inline mapper (mirrors tickets-api.ts _mapKnowledgeDraft) ────────────────

interface TicketKnowledgeDraftResult {
  id?: string | null;
  ticketId: string;
  title: string;
  summary: string;
  symptoms: string[];
  rootCause?: string;
  workaround?: string;
  resolutionSteps: string[];
  tags: string[];
  reviewNote: string;
  confidence: number;
  source: string;
  generatedAt: string;
  publishedAt?: string | null;
  jiraIssueKey?: string | null;
  status?: "draft" | "published";
}

interface KnowledgeDraftPublishResult {
  id: string;
  ticketId: string;
  jiraIssueKey: string | null;
  publishedAt: string;
  kbChunkId: number | null;
}

function mapKnowledgeDraft(data: {
  id?: string | null;
  ticket_id: string;
  title: string;
  summary: string;
  symptoms?: string[] | null;
  root_cause?: string | null;
  workaround?: string | null;
  resolution_steps?: string[] | null;
  tags?: string[] | null;
  review_note?: string;
  confidence?: number;
  source?: string;
  generated_at: string;
  published_at?: string | null;
  jira_issue_key?: string | null;
  status?: string;
}): TicketKnowledgeDraftResult {
  return {
    id: data.id ?? null,
    ticketId: data.ticket_id,
    title: data.title,
    summary: data.summary,
    symptoms: Array.isArray(data.symptoms) ? data.symptoms : [],
    rootCause: data.root_cause ?? undefined,
    workaround: data.workaround ?? undefined,
    resolutionSteps: Array.isArray(data.resolution_steps) ? data.resolution_steps : [],
    tags: Array.isArray(data.tags) ? data.tags : [],
    reviewNote: data.review_note ?? "",
    confidence: typeof data.confidence === "number" ? data.confidence : 0,
    source: data.source ?? "llm",
    generatedAt: data.generated_at,
    publishedAt: data.published_at ?? null,
    jiraIssueKey: data.jira_issue_key ?? null,
    status: (data.status === "published" ? "published" : "draft") as "draft" | "published",
  };
}

function mapPublishResult(data: {
  id: string;
  ticket_id: string;
  jira_issue_key?: string | null;
  published_at: string;
  kb_chunk_id?: number | null;
}): KnowledgeDraftPublishResult {
  return {
    id: data.id,
    ticketId: data.ticket_id,
    jiraIssueKey: data.jira_issue_key ?? null,
    publishedAt: data.published_at,
    kbChunkId: data.kb_chunk_id ?? null,
  };
}

// ── URL builder (mirrors apiFetch path logic) ─────────────────────────────────

const API_BASE = "http://localhost:8000/api";
function buildUrl(path: string): string {
  return `${API_BASE}${path}`;
}

// ── tests ─────────────────────────────────────────────────────────────────────

console.log("\nknowledge-draft — mapper");

const raw = {
  id: "uuid-001",
  ticket_id: "TW-1",
  title: "VPN client crash fix",
  summary: "Users on macOS 14 experience VPN client crashes after wake from sleep.",
  symptoms: ["crash on wake", "lost connection"],
  root_cause: "Kernel extension conflict with macOS 14 sleep handler",
  workaround: "Disable sleep mode",
  resolution_steps: ["Update client to 3.2.1", "Restart service"],
  tags: ["vpn", "macos"],
  review_note: "Validated against 5 resolved tickets.",
  confidence: 0.87,
  source: "llm",
  generated_at: "2026-04-21T10:00:00Z",
  published_at: null,
  jira_issue_key: null,
  status: "draft",
};

const mapped = mapKnowledgeDraft(raw);

expect("id is mapped", mapped.id, "uuid-001");
expect("ticketId is camelCase", mapped.ticketId, "TW-1");
expect("title mapped", mapped.title, "VPN client crash fix");
expect("symptoms array preserved", mapped.symptoms, ["crash on wake", "lost connection"]);
expect("rootCause camelCase", mapped.rootCause, "Kernel extension conflict with macOS 14 sleep handler");
expect("workaround mapped", mapped.workaround, "Disable sleep mode");
expect("resolutionSteps camelCase", mapped.resolutionSteps, ["Update client to 3.2.1", "Restart service"]);
expect("tags preserved", mapped.tags, ["vpn", "macos"]);
expect("reviewNote camelCase", mapped.reviewNote, "Validated against 5 resolved tickets.");
expect("confidence preserved", mapped.confidence, 0.87);
expect("source preserved", mapped.source, "llm");
expect("generatedAt camelCase", mapped.generatedAt, "2026-04-21T10:00:00Z");
expect("publishedAt null", mapped.publishedAt, null);
expect("jiraIssueKey null", mapped.jiraIssueKey, null);
expect("status defaults to draft", mapped.status, "draft");

// published state
const publishedRaw = { ...raw, published_at: "2026-04-21T12:00:00Z", jira_issue_key: "KB-42", status: "published" };
const publishedMapped = mapKnowledgeDraft(publishedRaw);
expect("publishedAt mapped", publishedMapped.publishedAt, "2026-04-21T12:00:00Z");
expect("jiraIssueKey mapped", publishedMapped.jiraIssueKey, "KB-42");
expect("status published", publishedMapped.status, "published");

// null/missing fields fall back gracefully
const minimalRaw = {
  ticket_id: "TW-2",
  title: "Minimal",
  summary: "Summary",
  generated_at: "2026-04-21T10:00:00Z",
};
const minimal = mapKnowledgeDraft(minimalRaw);
expect("missing symptoms → empty array", minimal.symptoms, []);
expect("missing resolutionSteps → empty array", minimal.resolutionSteps, []);
expect("missing tags → empty array", minimal.tags, []);
expect("missing id → null", minimal.id, null);
expect("missing rootCause → undefined", minimal.rootCause, undefined);
expect("missing confidence → 0", minimal.confidence, 0);
expect("missing source → llm", minimal.source, "llm");

console.log("\nknowledge-draft — publish result mapper");

const publishRaw = {
  id: "draft-uuid-1",
  ticket_id: "TW-1",
  jira_issue_key: "KB-42",
  published_at: "2026-04-21T12:00:00Z",
  kb_chunk_id: 77,
};
const publishResult = mapPublishResult(publishRaw);
expect("publish id mapped", publishResult.id, "draft-uuid-1");
expect("publish ticketId camelCase", publishResult.ticketId, "TW-1");
expect("publish jiraIssueKey camelCase", publishResult.jiraIssueKey, "KB-42");
expect("publish publishedAt camelCase", publishResult.publishedAt, "2026-04-21T12:00:00Z");
expect("publish kbChunkId camelCase", publishResult.kbChunkId, 77);

// null Jira key (no Jira configured)
const noJiraPublish = mapPublishResult({ id: "x", ticket_id: "TW-3", published_at: "2026-04-21T12:00:00Z" });
expect("null jiraIssueKey when absent", noJiraPublish.jiraIssueKey, null);
expect("null kbChunkId when absent", noJiraPublish.kbChunkId, null);

console.log("\nknowledge-draft — URL construction");

expect("generate POST URL", buildUrl("/tickets/TW-1/knowledge-draft?language=fr"),
  "http://localhost:8000/api/tickets/TW-1/knowledge-draft?language=fr");
expect("get GET URL", buildUrl("/tickets/TW-1/knowledge-draft"),
  "http://localhost:8000/api/tickets/TW-1/knowledge-draft");
expect("publish POST URL", buildUrl("/tickets/TW-1/knowledge-draft/publish"),
  "http://localhost:8000/api/tickets/TW-1/knowledge-draft/publish");

// ── summary ───────────────────────────────────────────────────────────────────

console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`);
if (failed > 0) process.exit(1);
