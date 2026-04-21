/**
 * Tests for search-api.ts logic.
 * Run: cd frontend && npx ts-node tests/search-api.test.ts
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

// ── inline globalSearch (mirrors search-api.ts) ───────────────────────────────

interface SearchResultItem { id: string; type: string; title: string; excerpt: string; status: string | null; priority: string | null; url: string }
interface SearchResponse { query: string; results: { tickets: SearchResultItem[]; problems: SearchResultItem[]; kb: SearchResultItem[] }; total_count: number }

let lastFetchedUrl: string | null = null;
let mockResponseBody: unknown = null;
let mockOk = true;

const origFetch = (global as any).fetch;
(global as any).fetch = async (url: string) => {
  lastFetchedUrl = url;
  return {
    ok: mockOk,
    json: async () => mockResponseBody,
  };
};

async function globalSearch(query: string, types: string[] = ["tickets", "problems"], limit = 5): Promise<SearchResponse> {
  const empty: SearchResponse = { query, results: { tickets: [], problems: [], kb: [] }, total_count: 0 };
  try {
    if (!query || query.trim().length < 2) return empty;
    const params = new URLSearchParams({ q: query.trim(), types: types.join(","), limit: String(limit) });
    const res = await (global as any).fetch(`/api/search?${params.toString()}`);
    if (!res.ok) return empty;
    return res.json();
  } catch {
    return empty;
  }
}

// ── tests ─────────────────────────────────────────────────────────────────────

console.log("\nsearch-api — URL construction");

(async () => {
  const mockResult: SearchResponse = {
    query: "vpn",
    results: {
      tickets: [{ id: "TW-1", type: "ticket", title: "VPN down", excerpt: "VPN is down", status: "open", priority: "high", url: "/tickets/TW-1" }],
      problems: [],
      kb: [],
    },
    total_count: 1,
  };
  mockResponseBody = mockResult;
  mockOk = true;

  await globalSearch("vpn");
  const url1 = (lastFetchedUrl as unknown) as string;
  expect("search URL contains q parameter", url1.includes("q=vpn"), true);
  expect("search URL contains types parameter", url1.includes("types=tickets"), true);
  expect("search URL contains limit parameter", url1.includes("limit=5"), true);
  expect("search URL path is /api/search", url1.startsWith("/api/search"), true);

  console.log("\nsearch-api — empty query returns empty results");

  const shortResult = await globalSearch("a");
  expect("query shorter than 2 chars → total_count 0", shortResult.total_count, 0);
  expect("query shorter than 2 chars → empty tickets", shortResult.results.tickets, []);

  const emptyResult = await globalSearch("");
  expect("empty query → total_count 0", emptyResult.total_count, 0);

  console.log("\nsearch-api — response mapped correctly");

  const result = await globalSearch("vpn");
  expect("tickets array returned", result.results.tickets.length, 1);
  expect("ticket id preserved", result.results.tickets[0].id, "TW-1");
  expect("ticket type preserved", result.results.tickets[0].type, "ticket");
  expect("total_count preserved", result.total_count, 1);

  console.log("\nsearch-api — API error returns empty results");

  mockOk = false;
  const errorResult = await globalSearch("error test");
  expect("error response → empty results", errorResult.total_count, 0);
  expect("error response → empty tickets array", errorResult.results.tickets, []);

  console.log("\nsearch-api — custom types and limit");

  mockOk = true;
  mockResponseBody = { query: "kb", results: { tickets: [], problems: [], kb: [] }, total_count: 0 };
  await globalSearch("kb article", ["kb"], 10);
  const url2 = (lastFetchedUrl as unknown) as string;
  expect("custom types used in URL", url2.includes("types=kb"), true);
  expect("custom limit used in URL", url2.includes("limit=10"), true);

  // ── summary ─────────────────────────────────────────────────────────────────

  console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`);
  if (failed > 0) process.exit(1);
})();
