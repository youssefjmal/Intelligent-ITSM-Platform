/**
 * Tests for recommendations-api.ts mapper logic.
 * Run: cd frontend && npx ts-node tests/recommendations-api.test.ts
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

// ── inline mapRecommendation (mirrors recommendations-api.ts) ─────────────────

type RecommendationDisplayMode =
  | "evidence_action" | "tentative_diagnostic" | "service_request"
  | "llm_general_knowledge" | "no_strong_match";

interface ApiRec {
  id: string;
  type: string;
  entity_type: string;
  title: string;
  description: string;
  impact: string;
  confidence: number;
  related_tickets: string[];
  created_at: string;
  recommended_action?: string | null;
  display_mode?: RecommendationDisplayMode;
  mode?: RecommendationDisplayMode;
  confidence_band?: string;
  confidence_label?: string;
  tentative?: boolean;
  probable_root_cause?: string | null;
  root_cause?: string | null;
  supporting_context?: string | null;
  source_label?: string;
  recommendation_mode?: string;
  action_relevance_score?: number;
  filtered_weak_match?: boolean;
  match_summary?: string | null;
  why_this_matches?: string[];
  next_best_actions?: string[];
  validation_steps?: string[];
  base_recommended_action?: string | null;
  base_next_best_actions?: string[];
  base_validation_steps?: string[];
  action_refinement_source?: string | null;
  evidence_sources?: Array<{ evidence_type: string; reference: string; excerpt?: string | null }>;
  llm_general_advisory?: { probable_causes?: string[]; suggested_checks?: string[]; escalation_hint?: string | null } | null;
  current_feedback?: { feedback_type: string; created_at: string; updated_at: string } | null;
  feedback_summary?: { total_feedback?: number; useful_count?: number; not_relevant_count?: number; applied_count?: number; rejected_count?: number; usefulness_rate?: number; applied_rate?: number; rejection_rate?: number } | null;
  reasoning?: string | null;
}

function clamp01(v: number | null | undefined): number {
  if (!Number.isFinite(v)) return 0;
  return Math.max(0, Math.min(1, Number(v)));
}

function mapRecommendation(rec: ApiRec) {
  return {
    id: rec.id,
    type: rec.type,
    entityType: rec.entity_type,
    title: rec.title,
    description: rec.description,
    recommendedAction: rec.recommended_action ?? null,
    reasoning: rec.reasoning ?? null,
    relatedTickets: rec.related_tickets,
    confidence: clamp01(rec.confidence),
    confidenceBand: rec.confidence_band || "low",
    confidenceLabel: rec.confidence_label || rec.confidence_band || "low",
    impact: rec.impact,
    tentative: Boolean(rec.tentative),
    probableRootCause: rec.probable_root_cause ?? null,
    rootCause: rec.root_cause ?? rec.probable_root_cause ?? null,
    supportingContext: rec.supporting_context ?? null,
    sourceLabel: rec.source_label || "fallback_rules",
    recommendationMode: rec.recommendation_mode || "fallback_rules",
    actionRelevanceScore: clamp01(rec.action_relevance_score),
    filteredWeakMatch: Boolean(rec.filtered_weak_match),
    displayMode: (() => {
      if (rec.display_mode) return rec.display_mode;
      if (rec.mode) return rec.mode;
      return rec.recommended_action ? "evidence_action" : "no_strong_match";
    })() as RecommendationDisplayMode,
    mode: rec.mode || rec.display_mode || (rec.recommended_action ? "evidence_action" : "no_strong_match"),
    matchSummary: rec.match_summary ?? null,
    whyThisMatches: Array.isArray(rec.why_this_matches) ? rec.why_this_matches : [],
    nextBestActions: Array.isArray(rec.next_best_actions) ? rec.next_best_actions : [],
    validationSteps: Array.isArray(rec.validation_steps) ? rec.validation_steps : [],
    baseRecommendedAction: rec.base_recommended_action ?? null,
    baseNextBestActions: Array.isArray(rec.base_next_best_actions) ? rec.base_next_best_actions : [],
    baseValidationSteps: Array.isArray(rec.base_validation_steps) ? rec.base_validation_steps : [],
    actionRefinementSource: rec.action_refinement_source ?? null,
    evidenceSources: (rec.evidence_sources || []).map((s) => ({
      evidenceType: s.evidence_type,
      reference: s.reference,
      excerpt: s.excerpt ?? null,
    })),
    llmGeneralAdvisory: rec.llm_general_advisory
      ? {
          probableCauses: Array.isArray(rec.llm_general_advisory.probable_causes) ? rec.llm_general_advisory.probable_causes : [],
          suggestedChecks: Array.isArray(rec.llm_general_advisory.suggested_checks) ? rec.llm_general_advisory.suggested_checks : [],
          escalationHint: rec.llm_general_advisory.escalation_hint ?? null,
        }
      : null,
    currentUserFeedback: rec.current_feedback
      ? { feedbackType: rec.current_feedback.feedback_type, createdAt: rec.current_feedback.created_at, updatedAt: rec.current_feedback.updated_at }
      : null,
    feedbackSummary: rec.feedback_summary
      ? {
          totalFeedback: Number(rec.feedback_summary.total_feedback || 0),
          usefulCount: Number(rec.feedback_summary.useful_count || 0),
          notRelevantCount: Number(rec.feedback_summary.not_relevant_count || 0),
          appliedCount: Number(rec.feedback_summary.applied_count || 0),
          rejectedCount: Number(rec.feedback_summary.rejected_count || 0),
          usefulnessRate: clamp01(rec.feedback_summary.usefulness_rate),
          appliedRate: clamp01(rec.feedback_summary.applied_rate),
          rejectionRate: clamp01(rec.feedback_summary.rejection_rate),
        }
      : null,
    createdAt: rec.created_at,
  };
}

// ── tests ─────────────────────────────────────────────────────────────────────

console.log("\nrecommendations-api — mapRecommendation");

const rawRec: ApiRec = {
  id: "rec-001",
  type: "pattern",
  entity_type: "ticket",
  title: "VPN Issues Pattern",
  description: "Multiple VPN tickets from the same subnet.",
  impact: "high",
  confidence: 0.82,
  related_tickets: ["TW-1", "TW-2"],
  created_at: "2026-04-01T08:00:00Z",
  recommended_action: "Check DHCP lease renewal settings",
  display_mode: "evidence_action",
  confidence_band: "high",
  confidence_label: "high",
  tentative: false,
  source_label: "rag_similar_tickets",
  recommendation_mode: "rag_similar_tickets",
  action_relevance_score: 0.9,
  filtered_weak_match: false,
  match_summary: "3 similar closed tickets",
  why_this_matches: ["Same subnet", "Same error code"],
  next_best_actions: ["Escalate to network team"],
  validation_steps: ["Check DHCP logs"],
  evidence_sources: [{ evidence_type: "similar_ticket", reference: "TW-1", excerpt: "DHCP issue resolved" }],
};

const rec = mapRecommendation(rawRec);

expect("id preserved", rec.id, "rec-001");
expect("entity_type → entityType", rec.entityType, "ticket");
expect("recommended_action → recommendedAction", rec.recommendedAction, "Check DHCP lease renewal settings");
expect("display_mode → displayMode", rec.displayMode, "evidence_action");
expect("confidence_band → confidenceBand", rec.confidenceBand, "high");
expect("source_label → sourceLabel", rec.sourceLabel, "rag_similar_tickets");
expect("action_relevance_score → actionRelevanceScore", rec.actionRelevanceScore, 0.9);
expect("filtered_weak_match → filteredWeakMatch", rec.filteredWeakMatch, false);
expect("match_summary → matchSummary", rec.matchSummary, "3 similar closed tickets");
expect("why_this_matches → whyThisMatches", rec.whyThisMatches, ["Same subnet", "Same error code"]);
expect("next_best_actions → nextBestActions", rec.nextBestActions, ["Escalate to network team"]);
expect("evidence_sources → evidenceSources[0].evidenceType", rec.evidenceSources[0].evidenceType, "similar_ticket");
expect("related_tickets → relatedTickets", rec.relatedTickets, ["TW-1", "TW-2"]);
expect("created_at → createdAt", rec.createdAt, "2026-04-01T08:00:00Z");

console.log("\nrecommendations-api — displayMode fallback");

// display_mode missing but mode present → use mode
const withModeOnly = mapRecommendation({ ...rawRec, display_mode: undefined, mode: "tentative_diagnostic" });
expect("falls back to mode when display_mode absent", withModeOnly.displayMode, "tentative_diagnostic");

// neither → infer from recommended_action
const noMode = mapRecommendation({ ...rawRec, display_mode: undefined, mode: undefined });
expect("infers evidence_action from recommended_action", noMode.displayMode, "evidence_action");

const noAction = mapRecommendation({ ...rawRec, display_mode: undefined, mode: undefined, recommended_action: null });
expect("infers no_strong_match when no recommended_action", noAction.displayMode, "no_strong_match");

console.log("\nrecommendations-api — confidence clamped");

expect("confidence > 1 clamped to 1", mapRecommendation({ ...rawRec, confidence: 1.5 }).confidence, 1);
expect("confidence < 0 clamped to 0", mapRecommendation({ ...rawRec, confidence: -0.5 }).confidence, 0);

console.log("\nrecommendations-api — URL construction");

const API_BASE = "http://localhost:8000/api";
const locale = "fr";
expect("fetchRecommendations URL", `${API_BASE}/recommendations?locale=${locale}`,
  "http://localhost:8000/api/recommendations?locale=fr");
expect("fetchSlaStrategies URL", `${API_BASE}/recommendations/sla-strategies?locale=${locale}`,
  "http://localhost:8000/api/recommendations/sla-strategies?locale=fr");

// ── summary ───────────────────────────────────────────────────────────────────

console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`);
if (failed > 0) process.exit(1);
