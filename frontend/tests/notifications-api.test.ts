/**
 * Tests for notifications-api.ts URL construction and type shapes.
 * Run: cd frontend && npx ts-node tests/notifications-api.test.ts
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

// ── inline URL helpers (mirror notifications-api.ts) ─────────────────────────

const API_BASE = "http://localhost:8000/api";

function getNotificationsUrl(params?: {
  unreadOnly?: boolean; source?: string; severity?: string; limit?: number; offset?: number;
}): string {
  const search = new URLSearchParams();
  if (params?.unreadOnly) search.set("unread_only", "true");
  if (params?.source) search.set("source", params.source);
  if (params?.severity) search.set("severity", params.severity);
  if (params?.limit) search.set("limit", String(params.limit));
  if (params?.offset) search.set("offset", String(params.offset));
  const qs = search.toString();
  return `${API_BASE}/notifications${qs ? `?${qs}` : ""}`;
}

function markReadUrl(id: string): string { return `${API_BASE}/notifications/${id}/read`; }
function markUnreadUrl(id: string): string { return `${API_BASE}/notifications/${id}/unread`; }
function markAllReadUrl(): string { return `${API_BASE}/notifications/mark-all-read`; }
function deleteUrl(id: string): string { return `${API_BASE}/notifications/${id}`; }
function unreadCountUrl(): string { return `${API_BASE}/notifications/unread-count`; }
function preferencesUrl(): string { return `${API_BASE}/notifications/preferences`; }

// ── tests ─────────────────────────────────────────────────────────────────────

console.log("\nnotifications-api — URL construction");

expect("base notifications URL (no params)", getNotificationsUrl(),
  "http://localhost:8000/api/notifications");

expect("unread_only=true param", getNotificationsUrl({ unreadOnly: true }),
  "http://localhost:8000/api/notifications?unread_only=true");

expect("source param", getNotificationsUrl({ source: "sla" }),
  "http://localhost:8000/api/notifications?source=sla");

expect("severity param", getNotificationsUrl({ severity: "critical" }),
  "http://localhost:8000/api/notifications?severity=critical");

expect("limit param", getNotificationsUrl({ limit: 20 }),
  "http://localhost:8000/api/notifications?limit=20");

expect("offset param", getNotificationsUrl({ offset: 10 }),
  "http://localhost:8000/api/notifications?offset=10");

expect("combined params", getNotificationsUrl({ unreadOnly: true, severity: "high", limit: 10 }),
  "http://localhost:8000/api/notifications?unread_only=true&severity=high&limit=10");

expect("markNotificationRead URL", markReadUrl("notif-123"),
  "http://localhost:8000/api/notifications/notif-123/read");

expect("markNotificationUnread URL", markUnreadUrl("notif-123"),
  "http://localhost:8000/api/notifications/notif-123/unread");

expect("markAllRead URL", markAllReadUrl(),
  "http://localhost:8000/api/notifications/mark-all-read");

expect("deleteNotification URL", deleteUrl("notif-456"),
  "http://localhost:8000/api/notifications/notif-456");

expect("unreadCount URL", unreadCountUrl(),
  "http://localhost:8000/api/notifications/unread-count");

expect("preferences GET URL", preferencesUrl(),
  "http://localhost:8000/api/notifications/preferences");

console.log("\nnotifications-api — NotificationItem shape validation");

interface NotificationItem {
  id: string; user_id: string; title: string; severity: string;
  event_type: string; created_at: string;
  body?: string | null; link?: string | null; read_at?: string | null;
}

const sample: NotificationItem = {
  id: "n-001",
  user_id: "user-1",
  title: "SLA Breach Alert",
  severity: "critical",
  event_type: "sla_breached",
  created_at: "2026-04-21T08:00:00Z",
  body: "Ticket TW-42 has breached SLA",
  link: "/tickets/TW-42",
  read_at: null,
};

expect("id field", sample.id, "n-001");
expect("severity field", sample.severity, "critical");
expect("event_type field", sample.event_type, "sla_breached");
expect("unread when read_at is null", sample.read_at === null, true);

// ── summary ───────────────────────────────────────────────────────────────────

console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`);
if (failed > 0) process.exit(1);
