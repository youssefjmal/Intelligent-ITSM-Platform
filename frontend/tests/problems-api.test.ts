/**
 * Tests for problems-api.ts mapper logic.
 * Run: cd frontend && npx ts-node tests/problems-api.test.ts
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

// ── inline mapProblem (mirrors problems-api.ts) ───────────────────────────────

interface ApiProblem {
  id: string;
  title: string;
  category: string;
  status: string;
  created_at: string;
  updated_at: string;
  occurrences_count: number;
  active_count: number;
  similarity_key: string;
  last_seen_at?: string | null;
  resolved_at?: string | null;
  root_cause?: string | null;
  workaround?: string | null;
  permanent_fix?: string | null;
  assignee?: string | null;
}

interface ProblemListItem {
  id: string;
  title: string;
  category: string;
  status: string;
  createdAt: string;
  updatedAt: string;
  occurrencesCount: number;
  activeCount: number;
  similarityKey: string;
  lastSeenAt?: string;
  resolvedAt?: string;
  rootCause?: string;
  workaround?: string;
  permanentFix?: string;
  assignee?: string;
}

function mapProblem(problem: ApiProblem): ProblemListItem {
  return {
    id: problem.id,
    title: problem.title,
    category: problem.category,
    status: problem.status,
    createdAt: problem.created_at,
    updatedAt: problem.updated_at,
    lastSeenAt: problem.last_seen_at ?? undefined,
    resolvedAt: problem.resolved_at ?? undefined,
    occurrencesCount: problem.occurrences_count,
    activeCount: problem.active_count,
    rootCause: problem.root_cause ?? undefined,
    workaround: problem.workaround ?? undefined,
    permanentFix: problem.permanent_fix ?? undefined,
    similarityKey: problem.similarity_key,
    assignee: problem.assignee ?? undefined,
  };
}

const PROBLEM_AI_FALLBACK_CONFIDENCE_START = 82;
const PROBLEM_AI_FALLBACK_CONFIDENCE_STEP = 6;
const PROBLEM_AI_FALLBACK_CONFIDENCE_MIN = 55;

function scoreProblemSuggestions(suggestions: string[]): Array<{ text: string; confidence: number }> {
  return suggestions
    .map((text, index) => ({
      text: String(text || "").trim(),
      confidence: Math.max(PROBLEM_AI_FALLBACK_CONFIDENCE_MIN, PROBLEM_AI_FALLBACK_CONFIDENCE_START - index * PROBLEM_AI_FALLBACK_CONFIDENCE_STEP),
    }))
    .filter((item) => item.text.length > 0);
}

const API_BASE = "http://localhost:8000/api";
function buildUrl(path: string): string { return `${API_BASE}${path}`; }

// ── tests ─────────────────────────────────────────────────────────────────────

console.log("\nproblems-api — mapProblem");

const rawProblem: ApiProblem = {
  id: "PB-1",
  title: "Recurring VPN drops",
  category: "network",
  status: "investigating",
  created_at: "2026-03-01T10:00:00Z",
  updated_at: "2026-04-01T10:00:00Z",
  occurrences_count: 14,
  active_count: 3,
  similarity_key: "vpn_drops_network",
  last_seen_at: "2026-04-20T15:00:00Z",
  resolved_at: null,
  root_cause: "DHCP lease expiry",
  workaround: "Reconnect VPN client",
  permanent_fix: null,
  assignee: "alice",
};

const problem = mapProblem(rawProblem);

expect("id preserved", problem.id, "PB-1");
expect("title preserved", problem.title, "Recurring VPN drops");
expect("created_at → createdAt", problem.createdAt, "2026-03-01T10:00:00Z");
expect("updated_at → updatedAt", problem.updatedAt, "2026-04-01T10:00:00Z");
expect("occurrences_count → occurrencesCount", problem.occurrencesCount, 14);
expect("active_count → activeCount", problem.activeCount, 3);
expect("similarity_key → similarityKey", problem.similarityKey, "vpn_drops_network");
expect("last_seen_at → lastSeenAt", problem.lastSeenAt, "2026-04-20T15:00:00Z");
expect("root_cause → rootCause", problem.rootCause, "DHCP lease expiry");
expect("workaround preserved", problem.workaround, "Reconnect VPN client");
expect("null permanent_fix → undefined", problem.permanentFix, undefined);
expect("null resolved_at → undefined", problem.resolvedAt, undefined);
expect("assignee preserved", problem.assignee, "alice");

console.log("\nproblems-api — null/missing fields");

const minimal: ApiProblem = {
  id: "PB-2", title: "Minimal", category: "application", status: "open",
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  occurrences_count: 1, active_count: 1, similarity_key: "key",
};
const m = mapProblem(minimal);
expect("missing root_cause → undefined", m.rootCause, undefined);
expect("missing assignee → undefined", m.assignee, undefined);
expect("missing lastSeenAt → undefined", m.lastSeenAt, undefined);

console.log("\nproblems-api — scoreProblemSuggestions");

const suggestions = ["Check DHCP logs", "Restart VPN service", "Update firmware", "Patch OS"];
const scored = scoreProblemSuggestions(suggestions);
expect("first suggestion confidence is 82", scored[0].confidence, 82);
expect("second suggestion confidence is 76", scored[1].confidence, 76);
expect("fourth suggestion confidence is max(55, 82-18=64)", scored[3].confidence, 64);
expect("empty strings filtered out", scoreProblemSuggestions([""]).length, 0);

console.log("\nproblems-api — URL construction");

expect("fetchProblems base URL", buildUrl("/problems"), "http://localhost:8000/api/problems");
expect("fetchProblem by id URL", buildUrl("/problems/PB-1"), "http://localhost:8000/api/problems/PB-1");

// ── summary ───────────────────────────────────────────────────────────────────

console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`);
if (failed > 0) process.exit(1);
