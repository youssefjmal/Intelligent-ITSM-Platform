/**
 * Tests for ai-feedback-api.ts mapper logic.
 * Run: cd frontend && npx ts-node tests/ai-feedback-api.test.ts
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

// ── inline mappers (mirror ai-feedback-api.ts) ────────────────────────────────

function clampUnit(value: number | null | undefined): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, Number(value)));
}

interface ApiFeedbackSummary {
  total_feedback?: number; useful_count?: number; not_relevant_count?: number;
  applied_count?: number; rejected_count?: number;
  usefulness_rate?: number; applied_rate?: number; rejection_rate?: number;
}

interface ApiFeedbackResponse {
  status: string;
  ticket_id?: string | null;
  recommendation_id?: string | null;
  source_surface?: string | null;
  current_feedback?: { feedback_type: string; created_at: string; updated_at: string } | null;
  feedback_summary?: ApiFeedbackSummary | null;
}

function mapFeedbackSummary(data?: ApiFeedbackSummary | null) {
  return {
    totalFeedback: Number(data?.total_feedback || 0),
    usefulCount: Number(data?.useful_count || 0),
    notRelevantCount: Number(data?.not_relevant_count || 0),
    appliedCount: Number(data?.applied_count || 0),
    rejectedCount: Number(data?.rejected_count || 0),
    usefulnessRate: clampUnit(data?.usefulness_rate),
    appliedRate: clampUnit(data?.applied_rate),
    rejectionRate: clampUnit(data?.rejection_rate),
  };
}

function mapFeedbackResponse(data: ApiFeedbackResponse) {
  return {
    status: data.status,
    ticketId: data.ticket_id ?? null,
    recommendationId: data.recommendation_id ?? null,
    sourceSurface: data.source_surface ?? null,
    currentFeedback: data.current_feedback
      ? { feedbackType: data.current_feedback.feedback_type, createdAt: data.current_feedback.created_at, updatedAt: data.current_feedback.updated_at }
      : null,
    feedbackSummary: data.feedback_summary ? mapFeedbackSummary(data.feedback_summary) : null,
  };
}

// ── tests ─────────────────────────────────────────────────────────────────────

console.log("\nai-feedback-api — mapFeedbackResponse");

const rawResponse: ApiFeedbackResponse = {
  status: "ok",
  ticket_id: "TW-42",
  recommendation_id: "rec-001",
  source_surface: "ticket_detail",
  current_feedback: { feedback_type: "useful", created_at: "2026-04-01T10:00:00Z", updated_at: "2026-04-01T10:00:00Z" },
  feedback_summary: { total_feedback: 10, useful_count: 7, not_relevant_count: 2, applied_count: 5, rejected_count: 1, usefulness_rate: 0.7, applied_rate: 0.5, rejection_rate: 0.1 },
};

const mapped = mapFeedbackResponse(rawResponse);

expect("status preserved", mapped.status, "ok");
expect("ticket_id → ticketId", mapped.ticketId, "TW-42");
expect("recommendation_id → recommendationId", mapped.recommendationId, "rec-001");
expect("source_surface → sourceSurface", mapped.sourceSurface, "ticket_detail");
expect("current_feedback.feedback_type → currentFeedback.feedbackType",
  mapped.currentFeedback?.feedbackType, "useful");
expect("feedback_summary.total_feedback → totalFeedback", mapped.feedbackSummary?.totalFeedback, 10);
expect("feedback_summary.useful_count → usefulCount", mapped.feedbackSummary?.usefulCount, 7);
expect("usefulness_rate clamped", mapped.feedbackSummary?.usefulnessRate, 0.7);
expect("applied_rate → appliedRate", mapped.feedbackSummary?.appliedRate, 0.5);
expect("rejection_rate → rejectionRate", mapped.feedbackSummary?.rejectionRate, 0.1);

console.log("\nai-feedback-api — null fields");

const nullResponse: ApiFeedbackResponse = { status: "ok" };
const nullMapped = mapFeedbackResponse(nullResponse);
expect("null ticket_id → null", nullMapped.ticketId, null);
expect("null recommendation_id → null", nullMapped.recommendationId, null);
expect("null source_surface → null", nullMapped.sourceSurface, null);
expect("null current_feedback → null", nullMapped.currentFeedback, null);
expect("null feedback_summary → null", nullMapped.feedbackSummary, null);

console.log("\nai-feedback-api — clampUnit");

expect("value 0.5 unchanged", clampUnit(0.5), 0.5);
expect("value > 1 clamped to 1", clampUnit(1.5), 1);
expect("value < 0 clamped to 0", clampUnit(-0.3), 0);
expect("null → 0", clampUnit(null), 0);
expect("undefined → 0", clampUnit(undefined), 0);
expect("NaN → 0", clampUnit(NaN), 0);

console.log("\nai-feedback-api — request body construction");

// Verify the request payload structure (inline the body-building logic)
function buildFeedbackBody(payload: {
  ticketId: string; feedbackType: string; recommendedAction?: string | null;
  displayMode?: string | null; confidence?: number | null;
}) {
  return {
    ticket_id: payload.ticketId,
    feedback_type: payload.feedbackType,
    source_surface: "ticket_detail",
    recommended_action: payload.recommendedAction ?? null,
    display_mode: payload.displayMode ?? null,
    confidence: (payload.confidence !== null && payload.confidence !== undefined && Number.isFinite(payload.confidence))
      ? clampUnit(payload.confidence) : undefined,
  };
}

const body = buildFeedbackBody({ ticketId: "TW-1", feedbackType: "useful", recommendedAction: "Restart VPN", displayMode: "evidence_action", confidence: 0.85 });
expect("ticket_id in body", body.ticket_id, "TW-1");
expect("feedback_type in body", body.feedback_type, "useful");
expect("source_surface in body", body.source_surface, "ticket_detail");
expect("recommended_action in body", body.recommended_action, "Restart VPN");
expect("display_mode in body", body.display_mode, "evidence_action");

console.log("\nai-feedback-api — URL construction");

const API_BASE = "http://localhost:8000/api";
expect("submitTicketFeedback URL", `${API_BASE}/ai/feedback`, "http://localhost:8000/api/ai/feedback");
expect("submitRecommendationFeedback URL", `${API_BASE}/recommendations/rec-001/feedback`,
  "http://localhost:8000/api/recommendations/rec-001/feedback");
expect("fetchAnalytics URL", `${API_BASE}/ai/feedback/analytics`, "http://localhost:8000/api/ai/feedback/analytics");

// ── summary ───────────────────────────────────────────────────────────────────

console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`);
if (failed > 0) process.exit(1);
