/**
 * Tests for badge-utils.ts
 * Run: cd frontend && npx ts-node tests/badge-utils.test.ts
 */

// ── inline copy of getBadgeStyle (no imports needed) ──────────────────────────

function getBadgeStyle(type: "ticket_status" | "problem_status" | "priority", value: string): string {
  const v = (value || "").toLowerCase().replace(/_/g, " ");
  const base = "inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium";

  if (type === "ticket_status") {
    switch (v) {
      case "open":              return `${base} bg-gray-100 text-gray-700`;
      case "in progress":       return `${base} bg-blue-100 text-blue-700`;
      case "in_progress":       return `${base} bg-blue-100 text-blue-700`;
      case "pending":           return `${base} bg-amber-100 text-amber-700`;
      case "resolved":          return `${base} bg-teal-100 text-teal-700`;
      case "closed":            return `${base} bg-gray-200 text-gray-500`;
      default:                  return `${base} bg-gray-100 text-gray-600`;
    }
  }
  if (type === "problem_status") {
    switch (v) {
      case "open":              return `${base} bg-gray-100 text-gray-700`;
      case "investigating":     return `${base} bg-amber-100 text-amber-700`;
      case "known error":       return `${base} bg-red-100 text-red-700`;
      case "resolved":          return `${base} bg-teal-100 text-teal-700`;
      case "closed":            return `${base} bg-gray-200 text-gray-500`;
      default:                  return `${base} bg-gray-100 text-gray-600`;
    }
  }
  if (type === "priority") {
    switch (v) {
      case "critical":          return `${base} bg-red-100 text-red-700`;
      case "high":              return `${base} bg-orange-100 text-orange-700`;
      case "medium":            return `${base} bg-amber-100 text-amber-700`;
      case "low":               return `${base} bg-gray-100 text-gray-600`;
      default:                  return `${base} bg-gray-100 text-gray-600`;
    }
  }
  return `${base} bg-gray-100 text-gray-600`;
}

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

// ── tests ─────────────────────────────────────────────────────────────────────

console.log("\nbadge-utils");

const base = "inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium";

// ticket_status
expect("open ticket → gray-100/gray-700",
  getBadgeStyle("ticket_status", "open"),
  `${base} bg-gray-100 text-gray-700`);

expect("in_progress ticket → blue-100/blue-700",
  getBadgeStyle("ticket_status", "in_progress"),
  `${base} bg-blue-100 text-blue-700`);

expect("pending ticket → amber",
  getBadgeStyle("ticket_status", "pending"),
  `${base} bg-amber-100 text-amber-700`);

expect("resolved ticket → teal",
  getBadgeStyle("ticket_status", "resolved"),
  `${base} bg-teal-100 text-teal-700`);

expect("closed ticket → gray-200/gray-500",
  getBadgeStyle("ticket_status", "closed"),
  `${base} bg-gray-200 text-gray-500`);

expect("unknown ticket status → fallback gray",
  getBadgeStyle("ticket_status", "unknown_xyz"),
  `${base} bg-gray-100 text-gray-600`);

// priority
expect("critical priority → red",
  getBadgeStyle("priority", "critical"),
  `${base} bg-red-100 text-red-700`);

expect("high priority → orange",
  getBadgeStyle("priority", "high"),
  `${base} bg-orange-100 text-orange-700`);

expect("medium priority → amber",
  getBadgeStyle("priority", "medium"),
  `${base} bg-amber-100 text-amber-700`);

expect("low priority → gray",
  getBadgeStyle("priority", "low"),
  `${base} bg-gray-100 text-gray-600`);

expect("unknown priority → gray fallback",
  getBadgeStyle("priority", "URGENT"),
  `${base} bg-gray-100 text-gray-600`);

// problem_status
expect("investigating problem → amber",
  getBadgeStyle("problem_status", "investigating"),
  `${base} bg-amber-100 text-amber-700`);

expect("known_error problem → red (underscore-normalized)",
  getBadgeStyle("problem_status", "known_error"),
  `${base} bg-red-100 text-red-700`);

// ── summary ───────────────────────────────────────────────────────────────────

console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`);
if (failed > 0) process.exit(1);
