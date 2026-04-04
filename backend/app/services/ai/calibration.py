"""Shared calibration constants and helpers for AI retrieval and advice."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CONFIDENCE_HIGH_THRESHOLD = 0.78
CONFIDENCE_MEDIUM_THRESHOLD = 0.52
GUIDANCE_CONFIDENCE_THRESHOLD = 0.6
CHAT_KB_SEMANTIC_MIN_SCORE = 0.55
DEFAULT_RESOLVER_TOP_K = 5

RETRIEVAL_QUALITY_THRESHOLDS = {"low": 0.35, "medium": 0.55, "high": 0.72}
RETRIEVAL_CLUSTER_WEIGHT_BY_EVIDENCE_TYPE = {
    "resolved ticket": 1.0,
    "similar ticket": 0.92,
    "comment": 0.88,
    "KB article": 0.82,
    "related problem": 0.78,
}
RETRIEVAL_DEFAULT_EVIDENCE_WEIGHT = 0.8
RETRIEVAL_COHERENCE_WEIGHTS = {
    "base_score": 0.22,
    "context_score": 0.24,
    "title_overlap": 0.12,
    "lexical_overlap": 0.12,
    "strong_overlap": 0.18,
    "topic_overlap": 0.08,
}
RETRIEVAL_COHERENCE_TERM_CAPS = {
    "shared_signal_terms": (0.14, 0.04),
    "component_terms": (0.08, 0.04),
    "action_terms": (0.06, 0.03),
}
RETRIEVAL_COHERENCE_BONUSES = {
    "dominant_topic_match": 0.12,
    "dominant_domain_match": 0.06,
    "exact_strong_multi": 0.06,
    "exact_strong_single": 0.03,
    "exact_focus_multi": 0.04,
    "evidence_weight_factor": 0.02,
}
RETRIEVAL_COHERENCE_PENALTIES = {
    "generic_only_overlap": 0.28,
    "generic_overlap_without_signal": 0.14,
    "topic_mismatch": 0.34,
    "domain_mismatch": 0.24,
    "weak_signal_context_max": 0.28,
    "weak_signal_cap": 0.24,
    "minimal_signature_cap": 0.18,
}
RETRIEVAL_CLUSTER_THRESHOLDS = {
    "support_min_coherence": 0.42,
    "support_count_score": 0.46,
    "anchor_overlap": 0.18,
    "anchored_top_coherence": 0.68,
    "anchored_cluster_score": 0.38,
    "strong_top_coherence": 0.82,
    "strong_cluster_score": 0.7,
    "support_bonus_cap": 0.18,
    "support_bonus_step": 0.09,
    "dominant_topic_bonus": 0.04,
    "conflict_second_score": 0.42,
    "conflict_second_coherence": 0.56,
    "conflict_margin": 0.14,
    "conflict_ratio": 0.84,
}
RETRIEVAL_CONSENSUS_WEIGHTS = {
    "cluster_score": 0.4,
    "top_coherence": 0.3,
    "support_ratio": 0.2,
    "margin_ratio": 0.1,
    "raw_score": 0.45,
    "consensus_score": 0.55,
}
RETRIEVAL_CONTEXT_WEIGHTS = {
    "title_overlap": 0.28,
    "focus_overlap": 0.24,
    "lexical_overlap": 0.14,
    "strong_overlap": 0.2,
    "topic_overlap": 0.08,
}
RETRIEVAL_CONTEXT_BONUSES = {
    "exact_phrase_step": 0.03,
    "exact_phrase_cap": 0.12,
    "exact_strong_multi": 0.04,
}
RETRIEVAL_CONTEXT_PENALTIES = {
    "generic_lexical_penalty": 0.06,
    "topic_mismatch_penalty": 0.24,
    "domain_mismatch_penalty": 0.18,
    "contrast_topic_penalty": 0.28,
    "contrast_domain_penalty": 0.22,
}
RETRIEVAL_CONTEXT_GATE_THRESHOLDS = {
    "topic_mismatch_overlap": 0.12,
    "domain_mismatch_overlap": 0.12,
    "contrast_overlap_max": 0.16,
    "generic_context_min": 0.24,
    "context_pass_min": 0.2,
    "topic_context_title_overlap": 0.12,
    "topic_context_strong_overlap": 0.14,
    "semantic_score_min": 0.78,
    "semantic_lexical_overlap": 0.16,
}
RETRIEVAL_TICKET_STATUS_SCORES = {
    "resolved": 0.12,
    "closed": 0.12,
    "open": -0.08,
    "in_progress": -0.08,
    "waiting_for_customer": -0.08,
    "waiting_for_support_vendor": -0.08,
    "pending": -0.08,
}
RETRIEVAL_COMMENT_QUALITY = {
    "length_80": 0.25,
    "length_160": 0.2,
    "length_260": 0.1,
    "action_hit_step": 0.08,
    "action_hit_cap": 0.25,
    "outcome_hit_step": 0.1,
    "outcome_hit_cap": 0.25,
    "structure_hit_step": 0.08,
    "structure_hit_cap": 0.15,
}
RETRIEVAL_LOCAL_LEXICAL = {
    "score_min": 0.12,
    "query_exact_bonus": 0.08,
    "ticket_id_bonus": 0.15,
    "category_bonus": 0.03,
    "topic_mismatch_penalty": 0.2,
    "domain_mismatch_penalty": 0.14,
    "title_overlap": 0.34,
    "focus_overlap": 0.22,
    "lexical_overlap": 0.14,
    "strong_overlap": 0.2,
    "topic_overlap": 0.1,
}
RETRIEVAL_LOCAL_SEMANTIC = {
    "score_min": 0.35,
    "semantic_weight": 0.76,
    "context_weight": 0.18,
}
RETRIEVAL_PROBLEM_SEARCH = {
    "score_min": 0.18,
    "seed_score": 0.85,
}
RETRIEVAL_ISSUE_MATCH_BLEND = {
    "semantic_weight": 0.78,
    "context_weight": 0.16,
}
RETRIEVAL_KB_ARTICLE_BLEND = {
    "semantic_weight": 0.8,
    "context_weight": 0.2,
}
RETRIEVAL_SOLUTION_SCORE_WEIGHTS = {
    "semantic_weight": 0.4,
    "quality_weight": 0.34,
    "context_weight": 0.18,
}
RETRIEVAL_FEEDBACK_BONUS = {"cap": 0.12, "multiplier": 0.12}

ADVISOR_EVIDENCE_BASE_WEIGHTS = {
    "resolved ticket": 0.4,
    "similar ticket": 0.34,
    "KB article": 0.3,
    "comment": 0.26,
    "related problem": 0.22,
}
ADVISOR_SOURCE_LABEL_BONUS = {
    "hybrid_jira_local": 0.03,
    "jira_semantic": 0.025,
    "local_semantic": 0.02,
    "local_lexical": 0.015,
    "kb_empty": -0.05,
    "fallback_rules": -0.06,
}
ADVISOR_ALIGNMENT_THRESHOLDS = {
    "low_confidence": 0.56,
    "action_relevance": 0.22,
    "hard_action_relevance": 0.18,
}
ADVISOR_ACTIONABILITY_WEIGHTS = {
    "action_hit_cap": 0.7,
    "action_hit_step": 0.2,
    "outcome_hit_cap": 0.2,
    "outcome_hit_step": 0.08,
    "structure_hit_cap": 0.15,
    "structure_hit_step": 0.08,
    "generic_penalty_cap": 0.25,
    "generic_penalty_step": 0.12,
    "short_text_penalty": 0.1,
}
ADVISOR_FALLBACK_CONFIDENCE = {
    "insufficient_evidence": 0.16,
    "weak_match_filtered": 0.34,
    "fallback_diagnostic": 0.42,
    "cause_insufficient": 0.18,
}
ADVISOR_CAUSE_CONFIRMATION = {
    "supported_excerpt_coherence": 0.44,
    "supported_excerpt_overlap": 0.14,
    "supported_excerpt_relevance": 0.28,
    "supported_excerpt_relevance_strong": 0.42,
    "supported_excerpt_context_strong": 0.4,
    "candidate_gate_strong_overlap": 0.12,
    "candidate_gate_relevance": 0.22,
    "candidate_gate_confident": 0.24,
    "candidate_gate_coherence": 0.42,
    "support_agreement_coherence": 0.58,
}
ADVISOR_RELEVANCE_WEIGHTS = {
    "title_overlap": 0.24,
    "description_overlap": 0.16,
    "entity_overlap": 0.22,
    "noun_overlap": 0.12,
    "strong_overlap": 0.14,
    "topic_overlap": 0.08,
    "key_hit_step": 0.03,
    "key_hit_cap": 0.16,
    "strong_hit_step": 0.04,
    "strong_hit_cap": 0.12,
    "domain_or_category_bonus": 0.08,
    "topic_mismatch_penalty": 0.4,
    "domain_mismatch_penalty": 0.24,
    "weak_signal_cap": 0.09,
    "topic_cap": 0.14,
}
ADVISOR_ACTION_ALIGNMENT_WEIGHTS = {
    "relevance_weight": 0.6,
    "actionability_weight": 0.25,
    "primary_score_weight": 0.15,
    "score_cap": 0.92,
}
ADVISOR_CONFIDENCE_WEIGHTS = {
    "semantic_bonus_cap": 0.14,
    "lexical_bonus_cap": 0.12,
    "anchor_bonus": 0.06,
    "action_bonus_cap": 0.07,
    "support_bonus_cap": 0.08,
    "support_bonus_step": 0.04,
    "agreement_bonus": 0.1,
    "tentative_penalty": 0.25,
    "domain_mismatch_penalty": 0.4,
    "topic_mismatch_penalty": 0.34,
    "weak_lexical_penalty": 0.16,
    "medium_lexical_penalty": 0.08,
}

AI_SLA_PRIORITY_FACTORS = {
    "low": 0.2,
    "medium": 0.45,
    "high": 0.72,
    "critical": 1.0,
}
AI_SLA_BAND_THRESHOLDS = (
    (0.8, "critical"),
    (0.6, "high"),
    (0.3, "medium"),
    (0.0, "low"),
)
AI_SLA_BACKLOG_WEIGHTS = {"similar_incidents": 0.55, "assignee_load": 0.45}
AI_SLA_CONFIDENCE = {
    "base": 0.46,
    "ratio_known_bonus": 0.1,
    "inactivity_known_bonus": 0.08,
    "backlog_known_bonus": 0.08,
    "high_risk_bonus": 0.05,
    "medium_risk_bonus": 0.03,
    "ai_weight": 0.88,
    "ai_bias": 0.06,
}
AI_SLA_BLEND_WEIGHTS = {"deterministic": 0.68, "ai": 0.32}


# ---------------------------------------------------------------------------
# LLM general-knowledge advisory constants
# ---------------------------------------------------------------------------

# Display mode for LLM general-knowledge advisory.
# Used when retrieval returns no dominant cluster and the LLM fallback
# succeeds.  Sits below tentative_diagnostic in the trust hierarchy.
# Frontend must render this with distinct blue/info styling and must
# never show an Apply button on this card type.
DISPLAY_MODE_LLM_GENERAL = "llm_general_knowledge"

# Display mode string for no_strong_match (unchanged behaviour).
# Defined here so resolution_advisor.py can import it alongside
# DISPLAY_MODE_LLM_GENERAL without hardcoding strings in two places.
DISPLAY_MODE_NO_STRONG_MATCH = "no_strong_match"

# Timeout in seconds allowed for a single LLM general advisory call.
# If the LLM is slow or unavailable the fallback degrades to no_strong_match
# gracefully.  Increase only after load testing confirms the LLM can handle it.
LLM_GENERAL_ADVISORY_TIMEOUT_SECONDS = 8

# Confidence score assigned to ALL LLM general advisory responses.
# Fixed at 0.25 — never inferred from LLM output.
# Intentionally low: general IT knowledge has not been validated against
# this organisation's environment.
LLM_GENERAL_ADVISORY_CONFIDENCE = 0.25


# Maximum recommendations to return in a single chat response.
# Higher numbers make the response too long for a chat bubble.
# Agents who want the full list should use /recommendations page.
MAX_CHAT_RECOMMENDATIONS = 5

# Maximum age of a cached ticket summary before regeneration is triggered.
# Set to 60 minutes — balances freshness with LLM call cost.
SUMMARY_CACHE_TTL_MINUTES = 60

# Maximum similar tickets used as RAG context for summarization.
# 3 is the sweet spot for qwen3:4b context window vs quality tradeoff.
SUMMARY_MAX_SIMILAR_TICKETS = 3

# Maximum character length of a generated summary.
# Summaries over this length are truncated before storage.
SUMMARY_MAX_LENGTH_CHARS = 500


def clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def confidence_band(value: float) -> str:
    score = clamp_unit(value)
    if score >= CONFIDENCE_HIGH_THRESHOLD:
        return "high"
    if score >= CONFIDENCE_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def bounded_threshold(mapping: Mapping[str, float], key: str, *, fallback: float) -> float:
    return float(mapping.get(key, fallback))


def clamp_score(value: Any, *, floor: float = 0.0, ceiling: float = 1.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = floor
    return max(floor, min(ceiling, numeric))


# Minimum similarity score to flag a ticket as a potential duplicate.
# Set conservatively — false positives are more disruptive than misses.
# Raise if too many irrelevant suggestions appear.
DUPLICATE_SIMILARITY_THRESHOLD = 0.72

# Maximum duplicate candidates to return per detection call.
# More than 3 overwhelms the agent and reduces the warning's impact.
MAX_DUPLICATE_CANDIDATES = 3

# Interval between proactive SLA monitor runs in seconds.
# 300 = every 5 minutes. Lower values increase DB query frequency.
# Do not set below 60 — SLA state changes rarely need sub-minute detection.
PROACTIVE_SLA_CHECK_INTERVAL_SECONDS = 300

# Elapsed ratio threshold above which a ticket is considered at_risk
# for proactive monitoring purposes.
# 0.75 = flag when 75% of SLA time is consumed.
PROACTIVE_SLA_AT_RISK_RATIO_THRESHOLD = 0.75

# Deduplication window for proactive SLA notifications in minutes.
# Prevents the monitor from creating multiple notifications for the
# same ticket within this window even if it runs multiple times.
PROACTIVE_SLA_DEDUP_WINDOW_MINUTES = 60
