"""Deterministic evidence-grounded incident resolution synthesis."""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.ai.calibration import (
    ADVISOR_ACTIONABILITY_WEIGHTS,
    ADVISOR_ACTION_ALIGNMENT_WEIGHTS,
    ADVISOR_ALIGNMENT_THRESHOLDS,
    ADVISOR_CAUSE_CONFIRMATION,
    ADVISOR_CONFIDENCE_WEIGHTS,
    ADVISOR_EVIDENCE_BASE_WEIGHTS as _EVIDENCE_BASE_WEIGHTS,
    ADVISOR_FALLBACK_CONFIDENCE,
    ADVISOR_RELEVANCE_WEIGHTS,
    ADVISOR_SOURCE_LABEL_BONUS as _SOURCE_LABEL_BONUS,
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
    DISPLAY_MODE_LLM_GENERAL as _DISPLAY_MODE_LLM_GENERAL,
    LLM_GENERAL_ADVISORY_CONFIDENCE as _LLM_ADVISORY_CONFIDENCE,
    confidence_band,
)
from app.services.ai.action_refiner import generate_low_trust_incident_actions

log = logging.getLogger(__name__)
from app.services.ai.retrieval import (
    candidate_topic_signature,
    cluster_evidence,
    evidence_conflict_detected,
    extract_evidence_features,
    score_candidate_coherence,
    select_primary_cluster,
)
from app.services.ai.taxonomy import (
    ACTION_HINTS as _ACTION_HINTS,
    CATEGORY_HINTS as _CATEGORY_HINTS,
    HIGH_SIGNAL_VOCAB as _HIGH_SIGNAL_VOCAB,
    LOW_SIGNAL_TOKENS as _LOW_SIGNAL_TOKENS,
    OUTCOME_HINTS as _OUTCOME_HINTS,
    TOPIC_HINTS as _TOPIC_HINTS,
    TOPIC_VOCAB as _TOPIC_VOCAB,
)
from app.services.ai.topic_templates import (
    topic_grounded_action_reasons,
    topic_grounded_action_templates,
    topic_safe_diagnostic_action,
    topic_supporting_context,
    topic_validation_actions,
    topic_validation_step,
)

@dataclass
class LLMGeneralAdvisory:
    """Advisory produced from LLM general IT knowledge when local evidence
    is insufficient to ground a specific recommendation.

    This is the lowest-trust output mode in the system.  It sits below
    tentative_diagnostic in the evidence hierarchy and must never be
    visually promoted above it in the frontend.

    This dataclass is only populated when:
    1. The retrieval pipeline returned no dominant cluster.
    2. display_mode would otherwise be no_strong_match.
    3. The LLM call succeeded and returned parseable output.

    Fields:
        probable_causes: 2-3 common causes for this category of issue,
            stated as possibilities, never as confirmed facts.
        suggested_checks: 2-4 diagnostic steps ordered from least
            invasive to most invasive.
        escalation_hint: Present only when priority is critical or high.
            Suggests when to escalate rather than continue diagnosing.
        knowledge_source: Always "llm_general_knowledge".  Used by the
            frontend to select the correct visual treatment and to ensure
            the Apply button is never shown on this card type.
        confidence: Always 0.25.  Fixed — never inferred from LLM output.
            General knowledge is never as reliable as local evidence.
        language: Language the response was generated in ("fr" or "en").
    """

    probable_causes: list[str]
    suggested_checks: list[str]
    escalation_hint: str | None
    knowledge_source: str = "llm_general_knowledge"
    confidence: float = _LLM_ADVISORY_CONFIDENCE
    language: str = "fr"


def _extract_concurrent_families(candidate_clusters: list[dict[str, Any]]) -> list[str]:
    """Extract topic families that were detected in retrieval but had no dominant cluster.

    Used to pass ambiguity context to the LLM general advisory prompt so the
    LLM can acknowledge that multiple domains were detected.

    Args:
        candidate_clusters: List of cluster dicts from _build_candidate_clusters().
            Each dict may contain ``dominant_topic``, ``cluster_id``, and
            ``signature_terms`` keys.  May be empty if retrieval returned no
            candidates.

    Returns:
        List of up to 5 family/topic strings, deduplicated, excluding the
        generic placeholder "generic".  Empty list if the input is empty or
        all entries are generic.
    """
    families: list[str] = []
    seen: set[str] = set()
    for cluster in (candidate_clusters or []):
        topic = str(cluster.get("dominant_topic") or cluster.get("cluster_id") or "").strip().lower()
        if topic and topic != "generic" and topic not in seen:
            seen.add(topic)
            families.append(topic)
    return families[:5]


def build_llm_general_advisory(
    ticket_title: str,
    ticket_description: str,
    ticket_category: str,
    ticket_priority: str,
    attempted_steps: list[str],
    concurrent_families: list[str],
    language: str = "fr",
) -> LLMGeneralAdvisory | None:
    """Call the LLM to produce a general-knowledge advisory when local
    evidence retrieval returns no dominant cluster.

    This function is the ONLY entry point for the LLM general advisory path.
    It enforces:
    - Fixed confidence of 0.25 regardless of LLM response content.
    - knowledge_source always set to "llm_general_knowledge".
    - Safe JSON parsing via json.loads() only — no ast.literal_eval().
    - Graceful None return on any failure — caller must handle None.

    The LLM output is validated before returning:
    - probable_causes must be a non-empty list.
    - suggested_checks must be a non-empty list.
    - Any item from attempted_steps found in suggested_checks is removed.
    - confidence is always overwritten to _LLM_ADVISORY_CONFIDENCE after parsing.

    Args:
        ticket_title: Ticket title.
        ticket_description: Ticket description (truncated to 600 chars
            inside the prompt builder to avoid context overflow).
        ticket_category: IT category string.
        ticket_priority: Priority string.
        attempted_steps: Already-tried steps to exclude from output.
        concurrent_families: Topic families from retrieval with no dominant
            cluster.  Passed to the prompt for context.
        language: Response language, "fr" or "en".  Defaults to "fr".

    Returns:
        LLMGeneralAdvisory if the LLM call succeeds and output is valid.
        None if the LLM is unavailable, times out, returns unparseable
        output, or returns empty lists for required fields.
        Caller must degrade gracefully when None is returned.

    Edge cases:
        - Returns None (not raises) on any exception, including network errors.
        - Empty string from LLM returns None.
        - JSON arrays / scalars instead of a dict return None.
        - escalation_hint is forced to None when empty string is returned.
    """
    from app.services.ai.llm import ollama_generate, extract_json
    from app.services.ai.prompts import build_general_advisory_prompt

    try:
        system_prompt, user_prompt = build_general_advisory_prompt(
            ticket_title=ticket_title,
            ticket_description=ticket_description,
            ticket_category=ticket_category,
            ticket_priority=ticket_priority,
            attempted_steps=attempted_steps,
            concurrent_families=concurrent_families,
            language=language,
        )
        # Combine system + user prompt into a single string for ollama_generate.
        combined_prompt = f"{system_prompt}\n\n{user_prompt}"
        raw = ollama_generate(combined_prompt, json_mode=True)

        if not raw:
            log.warning("build_llm_general_advisory: LLM returned empty response")
            return None

        parsed = extract_json(raw)
        if not isinstance(parsed, dict):
            log.warning(
                "build_llm_general_advisory: could not parse LLM output as dict. "
                "First 120 chars: %s",
                raw[:120],
            )
            return None

        probable_causes = parsed.get("probable_causes") or []
        suggested_checks = parsed.get("suggested_checks") or []
        escalation_hint = parsed.get("escalation_hint") or None

        if not isinstance(probable_causes, list):
            log.warning("build_llm_general_advisory: probable_causes is not a list")
            return None
        if not isinstance(suggested_checks, list):
            log.warning("build_llm_general_advisory: suggested_checks is not a list")
            return None

        # Remove any attempted steps that leaked into suggested_checks.
        if attempted_steps:
            attempted_lower = {s.lower() for s in attempted_steps}
            suggested_checks = [
                s for s in suggested_checks
                if not any(a in s.lower() for a in attempted_lower)
            ]

        # Normalise escalation_hint: blank string → None.
        if isinstance(escalation_hint, str) and not escalation_hint.strip():
            escalation_hint = None

        return LLMGeneralAdvisory(
            probable_causes=[str(c) for c in probable_causes[:3]],
            suggested_checks=[str(c) for c in suggested_checks[:4]],
            escalation_hint=str(escalation_hint) if escalation_hint else None,
            knowledge_source="llm_general_knowledge",
            confidence=_LLM_ADVISORY_CONFIDENCE,  # always fixed, never from LLM
            language=language,
        )

    except Exception:  # noqa: BLE001
        log.warning("build_llm_general_advisory: unexpected error", exc_info=True)
        return None


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_\-]{2,}", re.IGNORECASE)
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "issue",
    "ticket",
    "problem",
    "priority",
    "status",
    "category",
    "ticket_type",
}
_GENERIC_HINTS = (
    "follow best practices",
    "contact support",
    "investigate",
    "review logs",
    "check logs",
    "check the system",
    "monitor the system",
    "verify the configuration",
    "troubleshoot",
    "diagnose",
    "analyze",
    "analyse",
    "review the issue",
    "check the issue",
    "review the problem",
    "check the problem",
)
_GENERIC_ACTION_VERBS = {
    "check",
    "verify",
    "inspect",
    "review",
    "restart",
    "validate",
    "confirm",
    "monitor",
    "analyze",
    "analyse",
    "tester",
    "verifier",
    "inspecter",
    "controler",
}
_GENERIC_ACTION_PATTERNS = {
    "check logs",
    "review logs",
    "inspect logs",
    "verify the configuration",
    "check the configuration",
    "restart the service",
    "validate the issue",
    "confirm the issue",
}
_ROOT_CAUSE_PATTERNS = (
    re.compile(r"root cause[:\-\s]+(.+?)(?:[.;]|$)", re.IGNORECASE),
    re.compile(r"caused by[:\-\s]+(.+?)(?:[.;]|$)", re.IGNORECASE),
    re.compile(r"due to[:\-\s]+(.+?)(?:[.;]|$)", re.IGNORECASE),
    re.compile(r"because of[:\-\s]+(.+?)(?:[.;]|$)", re.IGNORECASE),
)
_ACTION_MARKER_PATTERNS = (
    re.compile(r"\b(?:resolved|fixed|mitigated|restored)\s+by\s+(.+?)(?:[.;]|$)", re.IGNORECASE),
    re.compile(r"\b(?:fix|solution|resolution|recommended action|action)\s*[:\-]\s*(.+?)(?:[.;]|$)", re.IGNORECASE),
)
_REFERENCE_PREFIX_PATTERNS = (
    re.compile(r"^\[[A-Z0-9\-_/]+\]\s*", re.IGNORECASE),
    re.compile(r"^(?:ticket|issue|problem|article|kb)\s+[A-Z0-9\-_/]+\s*[:\-]\s*", re.IGNORECASE),
    re.compile(r"^[A-Z]{2,}(?:-[A-Z0-9]+)+\s*[:\-]\s*", re.IGNORECASE),
    re.compile(r"^\d+[.)]\s*", re.IGNORECASE),
)
_ACTION_VERB_MAP = {
    "restarted": "restart",
    "rebooted": "reboot",
    "reset": "reset",
    "cleared": "clear",
    "flushed": "flush",
    "recreated": "recreate",
    "rebuilt": "rebuild",
    "updated": "update",
    "patched": "patch",
    "rolled back": "roll back",
    "replaced": "replace",
    "renewed": "renew",
    "reinstalled": "reinstall",
    "rotated": "rotate",
    "restored": "restore",
    "enabled": "enable",
    "disabled": "disable",
    "unlocked": "unlock",
    "removed": "remove",
    "added": "add",
    "assigned": "assign",
    "synced": "sync",
    "synchronized": "sync",
    "reimported": "reimport",
    "imported": "import",
    "applied": "apply",
    "switched": "switch",
    "moved": "move",
    "increased": "increase",
    "decreased": "decrease",
    "reconfigured": "reconfigure",
    "redeployed": "redeploy",
    "corrected": "correct",
    "aligned": "align",
    "realigned": "realign",
    "drained": "drain",
    "validated": "validate",
    "verified": "verify",
}
_MODE_BY_EVIDENCE = {
    "resolved ticket": "resolved_ticket_grounded",
    "similar ticket": "evidence_grounded",
    "KB article": "kb_grounded",
    "comment": "comment_grounded",
    "related problem": "evidence_grounded",
}
_NO_STRONG_MATCH_DISPLAY = "no_strong_match"
_TENTATIVE_DIAGNOSTIC_DISPLAY = "tentative_diagnostic"
_EVIDENCE_ACTION_DISPLAY = "evidence_action"
_ACTIVE_TICKET_STATUSES = {
    "open",
    "in_progress",
    "in-progress",
    "waiting_for_customer",
    "waiting-for-customer",
    "waiting_for_support_vendor",
    "waiting-for-support-vendor",
    "pending",
}
_TOPIC_DOMAIN_EXPECTATIONS = {
    "crm_integration": frozenset({"application", "infrastructure", "security"}),
    "mail_transport": frozenset({"email"}),
    "payroll_export": frozenset({"application"}),
    "network_access": frozenset({"network", "security"}),
    "database_data": frozenset({"application", "infrastructure"}),
    "notification_distribution": frozenset({"email", "application"}),
    "auth_path": frozenset({"security"}),
    # webhook_rotation is only valid in application/infrastructure domains — never in network/security/VPN
    "webhook_rotation": frozenset({"application", "infrastructure"}),
    # scheduled_maintenance is only valid as service_request or application
    "scheduled_maintenance": frozenset({"service_request", "application"}),
}
_WEAK_FAMILY_TOKENS = frozenset(
    {
        "token",
        "auth",
        "authentication",
        "error",
        "errors",
        "connection",
        "connections",
        "access",
        "policy",
        "service",
    }
)
_QUERY_TOPIC_SOURCE_WEIGHTS = {
    "strong_terms": 4.0,
    "focus_terms": 3.2,
    "title_tokens": 2.2,
    "tokens": 1.0,
}
_FAMILY_SELECTION_THRESHOLDS = {
    "score_min": 3.0,
    "structured_min": 2,
    "margin_min": 0.9,
    "high_score": 6.0,
    "high_explicit_hits": 2,
    "medium_score": 4.0,
    "broad_family_score": 4.8,
}
_AUTH_PATH_REQUIRED_ANCHORS = frozenset({"sso", "signin", "login", "certificate", "identity"})
_OPERATION_SIGNAL_HINTS = frozenset(
    {
        "sync",
        "export",
        "import",
        "login",
        "signin",
        "route",
        "routing",
        "delivery",
        "forwarding",
        "approval",
        "send",
        "reconnect",
        "query",
    }
)
_CONTEXT_SIGNAL_HINTS = frozenset(
    {
        "rotation",
        "rotate",
        "rotated",
        "update",
        "updated",
        "after",
        "fails",
        "fail",
        "stalls",
        "stalled",
        "timeout",
        "timeouts",
        "deferred",
        "denied",
        "missing",
        "expired",
    }
)
_AFFECTED_OBJECT_HINTS = frozenset(
    {
        "token",
        "credential",
        "secret",
        "certificate",
        "route",
        "gateway",
        "schema",
        "mapping",
        "date",
        "columns",
        "queue",
        "connector",
        "recipient",
        "workbook",
        "contact",
        "contacts",
        "mailbox",
    }
)

_TOPIC_HINT_FREQUENCY: dict[str, int] = {}
for _topic_hints in _TOPIC_HINTS.values():
    for _token in _topic_hints:
        _TOPIC_HINT_FREQUENCY[_token] = _TOPIC_HINT_FREQUENCY.get(_token, 0) + 1

_UNIQUE_TOPIC_HINTS = {
    topic: frozenset(
        token
        for token in hints
        if _TOPIC_HINT_FREQUENCY.get(token, 0) == 1 and token not in _LOW_SIGNAL_TOKENS and token not in _WEAK_FAMILY_TOKENS
    )
    for topic, hints in _TOPIC_HINTS.items()
}


@dataclass(slots=True)
class EvidenceCandidate:
    evidence_type: str
    reference: str
    excerpt: str
    source_id: str
    title: str | None
    score: float
    concrete: bool
    relevance: float
    lexical_overlap: float
    exact_focus_hits: int
    strong_overlap: float
    exact_strong_hits: int
    domain_mismatch: bool
    topic_mismatch: bool
    action_text: str | None
    context_score: float
    title_overlap: float
    topic_overlap: float
    cluster_id: str
    coherence_score: float


@dataclass(slots=True)
class GroundedActionStep:
    step: int
    text: str
    reason: str
    evidence: list[str]


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _truncate(value: str, *, limit: int = 220) -> str:
    text = _normalize_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(value or "")}


def _meaningful_tokens(value: str | None) -> set[str]:
    return {token for token in _tokens(value or "") if token not in _STOPWORDS}


def _overlap_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / max(1, len(left))


def _domain_signals(tokens: set[str]) -> set[str]:
    domains: set[str] = set()
    for category, hints in _CATEGORY_HINTS.items():
        if tokens.intersection(hints):
            domains.add(category)
    return domains


def _topic_signals(tokens: set[str]) -> set[str]:
    topics: set[str] = set()
    for topic, hints in _TOPIC_HINTS.items():
        if tokens.intersection(hints):
            topics.add(topic)
    return topics


def _ordered_topic_matches(tokens: set[str]) -> list[str]:
    scored: list[tuple[int, int, str]] = []
    for index, (topic, hints) in enumerate(_TOPIC_HINTS.items()):
        overlap = len(tokens.intersection(hints))
        if overlap:
            scored.append((overlap, index, topic))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [topic for _, _, topic in scored]


def _ordered_domain_matches(tokens: set[str]) -> list[str]:
    scored: list[tuple[int, int, str]] = []
    for index, (category, hints) in enumerate(_CATEGORY_HINTS.items()):
        overlap = len(tokens.intersection(hints))
        if overlap:
            scored.append((overlap, index, category))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [category for _, _, category in scored]


def _strong_signal_terms(tokens: set[str]) -> set[str]:
    return {token for token in tokens if token in _HIGH_SIGNAL_VOCAB and token not in _LOW_SIGNAL_TOKENS}


def _query_context(retrieval: dict[str, Any]) -> dict[str, Any]:
    context = retrieval.get("query_context")
    if isinstance(context, dict):
        tokens = [str(token).strip().lower() for token in list(context.get("tokens") or []) if str(token).strip()]
        title_tokens = [str(token).strip().lower() for token in list(context.get("title_tokens") or []) if str(token).strip()]
        focus_terms = [str(token).strip().lower() for token in list(context.get("focus_terms") or []) if str(token).strip()]
        metadata = dict(context.get("metadata") or {})
        context_tokens = set(tokens).union(_meaningful_tokens(str(metadata.get("category") or "").replace("_", " ")))
        strong_terms: list[str] = []
        seen_strong: set[str] = set()
        for token in [
            *[str(token).strip().lower() for token in list(context.get("strong_terms") or []) if str(token).strip()],
            *focus_terms,
            *title_tokens,
            *tokens,
        ]:
            if not token or token in seen_strong or token not in _HIGH_SIGNAL_VOCAB:
                continue
            seen_strong.add(token)
            strong_terms.append(token)
        topics = [str(token).strip().lower() for token in list(context.get("topics") or []) if str(token).strip()]
        if not topics:
            topics = _ordered_topic_matches(context_tokens)
        domains = [str(token).strip().lower() for token in list(context.get("domains") or []) if str(token).strip()]
        if not domains:
            domains = _ordered_domain_matches(context_tokens)
        return {
            "query": _normalize_text(context.get("query")),
            "title": _normalize_text(context.get("title")),
            "description": _normalize_text(context.get("description")),
            "tokens": tokens,
            "title_tokens": title_tokens,
            "focus_terms": focus_terms,
            "strong_terms": strong_terms[:10],
            "domains": domains,
            "topics": topics,
            "metadata": metadata,
        }
    query = _normalize_text(retrieval.get("query"))
    query_tokens = list(_meaningful_tokens(query))
    strong_terms = [token for token in query_tokens if token in _HIGH_SIGNAL_VOCAB][:10]
    topics = _ordered_topic_matches(set(query_tokens))
    return {
        "query": query,
        "title": query,
        "description": "",
        "tokens": query_tokens,
        "title_tokens": query_tokens[:6],
        "focus_terms": query_tokens[:6],
        "strong_terms": strong_terms,
        "domains": _ordered_domain_matches(set(query_tokens)),
        "topics": topics,
        "metadata": {},
    }


def _context_alignment(query_context: dict[str, Any], candidate_tokens: set[str]) -> dict[str, Any]:
    query_tokens = set(query_context.get("tokens") or [])
    title_tokens = set(query_context.get("title_tokens") or [])
    focus_terms = set(query_context.get("focus_terms") or [])
    strong_terms = set(query_context.get("strong_terms") or [])
    lexical_overlap = _overlap_score(query_tokens, candidate_tokens)
    title_overlap = _overlap_score(title_tokens, candidate_tokens)
    focus_overlap = _overlap_score(focus_terms, candidate_tokens)
    exact_focus_hits = len(focus_terms.intersection(candidate_tokens))
    strong_candidate_terms = _strong_signal_terms(candidate_tokens)
    strong_overlap = _overlap_score(strong_terms, strong_candidate_terms)
    exact_strong_hits = len(strong_terms.intersection(strong_candidate_terms))
    query_domains = set(query_context.get("domains") or [])
    query_topics = set(query_context.get("topics") or [])
    candidate_domains = _domain_signals(candidate_tokens)
    candidate_topics = _topic_signals(candidate_tokens)
    domain_mismatch = bool(query_domains and candidate_domains and query_domains.isdisjoint(candidate_domains))
    topic_mismatch = bool(query_topics and candidate_topics and query_topics.isdisjoint(candidate_topics))
    topic_overlap = (
        len(query_topics.intersection(candidate_topics)) / max(1, len(query_topics))
        if query_topics and candidate_topics
        else 0.0
    )
    return {
        "lexical_overlap": lexical_overlap,
        "title_overlap": title_overlap,
        "focus_overlap": focus_overlap,
        "exact_focus_hits": exact_focus_hits,
        "strong_overlap": strong_overlap,
        "exact_strong_hits": exact_strong_hits,
        "domain_mismatch": domain_mismatch,
        "topic_mismatch": topic_mismatch,
        "topic_overlap": topic_overlap,
    }


def _candidate_relevance(
    *,
    excerpt: str,
    reference: str,
    row: dict[str, Any],
    query_context: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    query_tokens = set(query_context.get("tokens") or [])
    title_tokens = set(query_context.get("title_tokens") or [])
    focus_terms = set(query_context.get("focus_terms") or [])
    if not query_tokens and not title_tokens and not focus_terms:
        fallback_relevance = max(float(row.get("context_score") or 0.0), 1.0)
        lexical_overlap = max(float(row.get("lexical_overlap") or 0.0), min(1.0, fallback_relevance * 0.6))
        return round(min(1.0, fallback_relevance), 4), {
            "context_score": round(min(1.0, fallback_relevance), 4),
            "lexical_overlap": round(max(0.0, min(1.0, lexical_overlap)), 4),
            "title_overlap": round(max(0.0, min(1.0, float(row.get("title_overlap") or 0.0))), 4),
            "exact_focus_hits": 0,
            "strong_overlap": round(max(0.0, min(1.0, float(row.get("strong_overlap") or 0.0))), 4),
            "exact_strong_hits": int(row.get("exact_strong_hits") or 0),
            "domain_mismatch": bool(row.get("domain_mismatch")),
            "topic_mismatch": bool(row.get("topic_mismatch")),
            "topic_overlap": round(max(0.0, min(1.0, float(row.get("topic_overlap") or 0.0))), 4),
        }
    candidate_tokens = _meaningful_tokens(f"{reference} {excerpt}")
    alignment = _context_alignment(query_context, candidate_tokens)
    domain_mismatch = bool(row.get("domain_mismatch")) or bool(alignment["domain_mismatch"])
    topic_mismatch = bool(row.get("topic_mismatch")) or bool(alignment["topic_mismatch"])
    computed = (
        (ADVISOR_RELEVANCE_WEIGHTS["title_overlap"] * float(alignment["title_overlap"]))
        + (ADVISOR_RELEVANCE_WEIGHTS["entity_overlap"] * float(alignment["focus_overlap"]))
        + (ADVISOR_RELEVANCE_WEIGHTS["noun_overlap"] * float(alignment["lexical_overlap"]))
        + (ADVISOR_RELEVANCE_WEIGHTS["strong_overlap"] * float(alignment["strong_overlap"]))
        + (ADVISOR_RELEVANCE_WEIGHTS["topic_overlap"] * float(alignment["topic_overlap"]))
    )
    if int(alignment["exact_strong_hits"]) >= 2:
        computed += ADVISOR_RELEVANCE_WEIGHTS["strong_hit_step"]
    if topic_mismatch:
        computed -= ADVISOR_RELEVANCE_WEIGHTS["domain_mismatch_penalty"]
    if domain_mismatch:
        computed -= ADVISOR_ALIGNMENT_THRESHOLDS["hard_action_relevance"]
    row_context = float(row.get("context_score") or 0.0)
    computed = max(0.0, min(1.0, computed))
    relevance = max(computed, min(row_context, computed + ADVISOR_RELEVANCE_WEIGHTS["strong_hit_cap"]))
    lexical = max(float(row.get("lexical_overlap") or 0.0), float(alignment["lexical_overlap"]))
    return round(relevance, 4), {
        "context_score": round(max(0.0, min(1.0, max(row_context, computed))), 4),
        "lexical_overlap": round(max(0.0, min(1.0, lexical)), 4),
        "title_overlap": round(max(0.0, min(1.0, float(alignment["title_overlap"]))), 4),
        "exact_focus_hits": int(alignment["exact_focus_hits"]),
        "strong_overlap": round(max(0.0, min(1.0, float(alignment["strong_overlap"]))), 4),
        "exact_strong_hits": int(alignment["exact_strong_hits"]),
        "domain_mismatch": domain_mismatch,
        "topic_mismatch": topic_mismatch,
        "topic_overlap": round(max(0.0, min(1.0, float(alignment["topic_overlap"]))), 4),
    }


def _candidate_cluster_metadata(
    *,
    query_context: dict[str, Any],
    reference: str,
    title: str | None,
    text: str,
    category_hint: str | None,
    action_text: str | None,
    evidence_type: str,
    base_score: float,
    metrics: dict[str, Any],
    row: dict[str, Any],
) -> tuple[str, float]:
    features = extract_evidence_features(
        query_context,
        title=title,
        text=text,
        category_hint=category_hint,
        action_text=action_text,
        reference=reference,
    )
    cluster_id = str(row.get("cluster_id") or "").strip().lower() or candidate_topic_signature(features)
    coherence_value = row.get("coherence_score")
    if coherence_value is None:
        coherence_value = score_candidate_coherence(
            query_context,
            features=features,
            metrics=metrics,
            base_score=base_score,
            evidence_type=evidence_type,
        )
    return cluster_id, round(float(coherence_value), 4)


def _actionability_score(text: str) -> float:
    lowered = _normalize_text(text).lower()
    if not lowered:
        return 0.0
    action_hits = sum(1 for token in _ACTION_HINTS if token in lowered)
    generic_hits = sum(1 for token in _GENERIC_HINTS if token in lowered)
    outcome_hits = sum(1 for token in _OUTCOME_HINTS if token in lowered)
    structure_hits = 0
    if any(marker in lowered for marker in ("1.", "2.", "first", "then", "after", "finally")):
        structure_hits += 1
    if ":" in lowered:
        structure_hits += 1

    score = 0.0
    score += min(ADVISOR_ACTIONABILITY_WEIGHTS["action_hit_cap"], action_hits * ADVISOR_ACTIONABILITY_WEIGHTS["action_hit_step"])
    score += min(ADVISOR_ACTIONABILITY_WEIGHTS["outcome_hit_cap"], outcome_hits * ADVISOR_ACTIONABILITY_WEIGHTS["outcome_hit_step"])
    score += min(ADVISOR_ACTIONABILITY_WEIGHTS["structure_hit_cap"], structure_hits * ADVISOR_ACTIONABILITY_WEIGHTS["structure_hit_step"])
    score -= min(ADVISOR_ACTIONABILITY_WEIGHTS["generic_penalty_cap"], generic_hits * ADVISOR_ACTIONABILITY_WEIGHTS["generic_penalty_step"])
    if len(lowered) < 20:
        score -= ADVISOR_ACTIONABILITY_WEIGHTS["short_text_penalty"]
    return max(0.0, min(1.0, score))


def _is_concrete_fix(text: str) -> bool:
    score = _actionability_score(text)
    return score >= 0.18


def _split_action_candidates(text: str) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    segments = [
        segment.strip(" -:")
        for segment in re.split(r"(?<=[.!?;])\s+|\n+", normalized)
        if segment.strip(" -:")
    ]
    return segments or [normalized]


def _strip_reference_prefix(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    updated = normalized
    changed = True
    while changed:
        changed = False
        for pattern in _REFERENCE_PREFIX_PATTERNS:
            stripped = pattern.sub("", updated, count=1).strip()
            if stripped != updated:
                updated = stripped
                changed = True
    return updated


def _clean_action_candidate(text: str) -> str:
    normalized = _strip_reference_prefix(text)
    normalized = re.sub(
        r"^(?:resolved by|fixed by|mitigated by|restored by|fix|solution|resolution|recommended action|action)\s*[:\-]?\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    return normalized.strip(" -:")


def _looks_like_reference_line(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    starts_with_reference = any(pattern.match(normalized) for pattern in _REFERENCE_PREFIX_PATTERNS[:3])
    if not starts_with_reference:
        return False
    lowered = normalized.lower()
    return not any(token in lowered for token in _ACTION_HINTS)


def _normalize_action_verbs(text: str) -> str:
    normalized = _clean_action_candidate(text)
    if not normalized:
        return ""
    for source, target in sorted(_ACTION_VERB_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.compile(rf"(?i)(^|(?:and|then|puis|et)\s+){re.escape(source)}\b")
        normalized = pattern.sub(lambda match: f"{match.group(1)}{target}", normalized)
    return normalized


def _finalize_action_text(text: str) -> str:
    normalized = _normalize_action_verbs(text)
    normalized = re.sub(r"\b(?:requester|user|owner)\s+confirmed\b.*$", "", normalized, flags=re.IGNORECASE).strip(" -:;,.")
    if not normalized:
        return ""
    normalized = normalized[0].upper() + normalized[1:]
    if normalized[-1] not in ".!?":
        normalized += "."
    return normalized


def _action_overlap_bonus(text: str, query_context: dict[str, Any]) -> float:
    focus_terms = set(query_context.get("focus_terms") or [])
    title_terms = set(query_context.get("title_tokens") or [])
    if not focus_terms and not title_terms:
        return 0.0
    candidate_tokens = _meaningful_tokens(text)
    if not candidate_tokens:
        return 0.0
    focus_overlap = _overlap_score(focus_terms, candidate_tokens)
    title_overlap = _overlap_score(title_terms, candidate_tokens)
    return min(0.22, (focus_overlap * 0.14) + (title_overlap * 0.08))


def _extract_fix_sentence(text: str, *, query_context: dict[str, Any] | None = None) -> str | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    candidates: list[tuple[float, str]] = []
    for pattern in _ACTION_MARKER_PATTERNS:
        for match in pattern.finditer(normalized):
            candidate = _finalize_action_text(match.group(1))
            if not candidate:
                continue
            score = 0.38 + (_actionability_score(candidate) * 0.4)
            if query_context is not None:
                score += _action_overlap_bonus(candidate, query_context)
            candidates.append((score, candidate))

    for segment in _split_action_candidates(normalized):
        if _looks_like_reference_line(segment):
            continue
        candidate = _finalize_action_text(segment)
        if not candidate:
            continue
        score = _actionability_score(candidate)
        if query_context is not None:
            score += _action_overlap_bonus(candidate, query_context)
        if any(marker.search(segment) for marker in _ACTION_MARKER_PATTERNS):
            score += 0.12
        candidates.append((score, candidate))

    if not candidates:
        return None
    best_score, best_candidate = max(candidates, key=lambda item: item[0])
    if best_score < 0.18:
        return None
    return best_candidate


def _texts_agree(left: str, right: str) -> bool:
    left_text = _normalize_text(left).lower()
    right_text = _normalize_text(right).lower()
    if not left_text or not right_text:
        return False
    if left_text in right_text or right_text in left_text:
        return True
    left_tokens = _tokens(left_text)
    right_tokens = _tokens(right_text)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens.intersection(right_tokens))
    return overlap >= 3 and (overlap / max(1, min(len(left_tokens), len(right_tokens)))) >= 0.35


def _ordered_query_terms(query_context: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    for key in ("strong_terms", "focus_terms", "title_tokens", "tokens"):
        for raw in list(query_context.get(key) or []):
            token = str(raw).strip().lower()
            if not token or token in ordered or token in _STOPWORDS:
                continue
            ordered.append(token)
    return ordered


def _display_term(token: str) -> str:
    cleaned = str(token or "").strip().replace("_", " ").replace("-", " ")
    return cleaned


def _match_terms(query_context: dict[str, Any], *texts: str, limit: int = 4) -> list[str]:
    candidate_tokens: set[str] = set()
    for raw in texts:
        candidate_tokens.update(_meaningful_tokens(raw))
    if not candidate_tokens:
        return []
    matched: list[str] = []
    for token in _ordered_query_terms(query_context):
        if token in candidate_tokens:
            display = _display_term(token)
            if display and display not in matched:
                matched.append(display)
        if len(matched) >= limit:
            break
    return matched


def _match_summary(query_context: dict[str, Any], primary: EvidenceCandidate, support: list[EvidenceCandidate], *, lang: str) -> str | None:
    terms = _match_terms(
        query_context,
        primary.reference,
        primary.action_text or "",
        primary.excerpt,
        *(item.action_text or item.excerpt for item in support[1:]),
    )
    if not terms:
        return None
    joined = ", ".join(terms[:4])
    if lang == "fr":
        return f"Correspondance sur {joined}."
    return f"Matched on {joined}."


def _problem_candidate_relevant_for_root_cause(candidate: EvidenceCandidate) -> bool:
    if candidate.topic_mismatch or candidate.domain_mismatch:
        return (
            candidate.exact_focus_hits >= 1
            or candidate.exact_strong_hits >= 1
            or candidate.strong_overlap >= 0.14
            or candidate.relevance >= 0.18
            or candidate.coherence_score >= 0.32
        )
    return True


def _problem_candidate_matches_selected_cluster(
    row: dict[str, Any],
    candidate: EvidenceCandidate,
    *,
    selected_cluster_id: str | None,
) -> bool:
    if not selected_cluster_id:
        return True
    explicit_problem_cluster_id = str(row.get("cluster_id") or "").strip().lower() or None
    derived_problem_cluster_id = str(row.get("_advisor_cluster_id") or "").strip().lower() or None
    if explicit_problem_cluster_id:
        return explicit_problem_cluster_id == selected_cluster_id
    if derived_problem_cluster_id == selected_cluster_id:
        return True
    if candidate.cluster_id == selected_cluster_id:
        return True
    if candidate.topic_mismatch or candidate.domain_mismatch:
        return False
    return (
        candidate.exact_focus_hits >= 1
        or candidate.exact_strong_hits >= 1
        or candidate.strong_overlap >= 0.18
        or candidate.relevance >= 0.22
        or candidate.coherence_score >= 0.45
    )


def build_root_cause(
    retrieval: dict[str, Any],
    *,
    primary: EvidenceCandidate,
    support: list[EvidenceCandidate],
    query_context: dict[str, Any],
    selected_cluster_id: str | None = None,
) -> tuple[str | None, str | None]:
    root_cause = None
    root_problem_ref = None
    for row in list(retrieval.get("related_problems") or []):
        problem_candidate = _candidate_from_problem(row, query_context=query_context)
        if problem_candidate is None or not _problem_candidate_relevant_for_root_cause(problem_candidate):
            continue
        # Root-cause text must stay inside the selected incident family.
        if not _problem_candidate_matches_selected_cluster(
            row,
            problem_candidate,
            selected_cluster_id=selected_cluster_id,
        ):
            continue
        root_text = _normalize_text(row.get("root_cause"))
        if root_text:
            root_cause = _truncate(root_text, limit=160)
            root_problem_ref = str(row.get("id") or row.get("title") or "").strip() or None
            break
    support_confirms_excerpt = any(
        candidate.reference != primary.reference
        and candidate.cluster_id == primary.cluster_id
        and not candidate.topic_mismatch
        and not candidate.domain_mismatch
        and candidate.coherence_score >= 0.34
        for candidate in support
    )
    excerpt_root_cause_supported = (
        primary.coherence_score >= 0.44
        and not primary.topic_mismatch
        and not primary.domain_mismatch
        and (
            primary.relevance >= 0.28
            or primary.context_score >= 0.28
            or primary.exact_focus_hits >= 1
            or primary.exact_strong_hits >= 1
            or primary.strong_overlap >= 0.14
        )
        and (support_confirms_excerpt or primary.relevance >= 0.42 or primary.context_score >= 0.4)
    )
    if not root_cause and excerpt_root_cause_supported:
        root_cause = _extract_root_cause_text(primary.excerpt, *(item.excerpt for item in support[1:]))
    if not root_cause and root_problem_ref is None and primary.relevance >= 0.5 and not primary.domain_mismatch and list(retrieval.get("related_problems") or []):
        fallback_problem = next(
            (
                row
                for row in list(retrieval.get("related_problems") or [])
                if _normalize_text(row.get("root_cause")) and float(row.get("similarity_score") or 0.0) >= 0.7
            ),
            None,
        )
        if fallback_problem is not None:
            root_cause = _truncate(_normalize_text(fallback_problem.get("root_cause")), limit=160)
            root_problem_ref = str(fallback_problem.get("id") or fallback_problem.get("title") or "").strip() or None
    return root_cause, root_problem_ref


def _subject_label(query_context: dict[str, Any], *, limit: int = 3) -> str:
    terms = [_display_term(token) for token in _ordered_query_terms(query_context)[:limit]]
    return ", ".join(term for term in terms if term)


def build_supporting_context(
    query_context: dict[str, Any],
    *,
    recommended_action: str | None,
    lang: str,
) -> str | None:
    action_tokens = _meaningful_tokens(recommended_action or "")
    tokens = set(_ordered_query_terms(query_context))
    if not tokens:
        return None
    for topic in ("network_access", "auth_path", "payroll_export", "mail_transport"):
        topic_hints = set(_TOPIC_HINTS.get(topic) or [])
        if tokens.intersection(topic_hints) and not action_tokens.intersection(topic_hints):
            return topic_supporting_context(topic, lang=lang)
    return None


def _evidence_reference_label(candidate: EvidenceCandidate) -> str:
    return f"{candidate.evidence_type}: {candidate.reference}"


def extract_ticket_operational_signals(
    query_context: dict[str, Any],
    *,
    primary: EvidenceCandidate,
    support: list[EvidenceCandidate],
    probable_root_cause: str | None,
) -> dict[str, Any]:
    evidence_texts = [
        primary.title or "",
        primary.excerpt,
        primary.action_text or "",
        probable_root_cause or "",
        *(candidate.title or "" for candidate in support[1:]),
        *(candidate.excerpt for candidate in support[1:]),
        *(candidate.action_text or "" for candidate in support[1:]),
    ]
    evidence_tokens = set()
    for text in evidence_texts:
        evidence_tokens.update(_meaningful_tokens(text))
    matched_terms = _match_terms(query_context, *evidence_texts, limit=6)
    query_terms = _ordered_query_terms(query_context)
    signal_tokens = evidence_tokens.union(query_terms)
    evidence_topics = list(_ordered_topic_matches(evidence_tokens))
    dominant_topic = next(
        (
            topic
            for topic in list(query_context.get("topics") or [])
            if topic in _TOPIC_HINTS and (topic == primary.cluster_id or topic in evidence_topics)
        ),
        None,
    )
    if not dominant_topic and primary.cluster_id in _TOPIC_HINTS:
        dominant_topic = primary.cluster_id
    if not dominant_topic:
        dominant_topic = next(iter(evidence_topics), None)
    if not dominant_topic:
        dominant_topic = next((topic for topic in list(query_context.get("topics") or []) if topic in _TOPIC_HINTS), None)
    topic_terms = list(_TOPIC_HINTS.get(dominant_topic or "", set()))
    subject = _subject_label(query_context) or ", ".join(matched_terms[:3])
    return {
        "dominant_topic": dominant_topic,
        "dominant_topic_overlap": dominant_topic,
        "query_terms": query_terms,
        "matched_terms": matched_terms,
        "combined_tokens": signal_tokens,
        "evidence_tokens": sorted(evidence_tokens),
        "subject": subject,
        "topic_terms": topic_terms,
        "primary_reference": primary.reference,
        "support_references": [candidate.reference for candidate in support[:3] if candidate.reference],
        "integration_auth": bool(
            evidence_tokens.intersection({"crm", "sync", "integration", "worker", "job", "scheduler"})
            and evidence_tokens.intersection({"token", "oauth", "credential", "secret", "auth", "authentication"})
        ),
        "export_mapping": bool(
            evidence_tokens.intersection({"export", "csv", "import", "workbook", "payroll"})
            and evidence_tokens.intersection({"date", "formatter", "parser", "serializer", "mapping", "schema"})
        ),
        "mail_routing": bool(
            evidence_tokens.intersection({"mail", "email", "relay", "connector", "mailbox"})
            and evidence_tokens.intersection({"forwarding", "distribution", "queue", "transport", "delivery", "connector", "relay"})
        ),
        "network_access": bool(
            evidence_tokens.intersection({"vpn", "remote", "tunnel", "gateway"})
            and evidence_tokens.intersection({"route", "routing", "dns", "mfa", "policy", "session"})
        ),
        "auth_path": bool(
            evidence_tokens.intersection({"auth", "authentication", "sso", "signin", "login"})
            or (
                evidence_tokens.intersection({"token", "certificate"})
                and evidence_tokens.intersection({"policy", "identity", "access", "auth", "authentication"})
            )
        ),
        "notification_distribution": bool(
            evidence_tokens.intersection({"notification", "distribution", "recipient", "approval", "manager", "notice"})
            and evidence_tokens.intersection({"notification", "distribution", "approval", "recipient"})
        ),
    }


def action_is_too_generic(action_text: str, query_context: dict[str, Any]) -> bool:
    normalized = _finalize_action_text(action_text) or _normalize_text(action_text)
    lowered = normalized.lower()
    if not lowered:
        return True
    if lowered in _GENERIC_ACTION_PATTERNS or any(lowered == hint for hint in _GENERIC_HINTS):
        return True
    tokens = _meaningful_tokens(normalized)
    if not tokens:
        return True
    contextual_tokens = set(query_context.get("strong_terms") or []).union(query_context.get("focus_terms") or []).union(query_context.get("tokens") or [])
    strong_hits = len(tokens.intersection(contextual_tokens.union(_HIGH_SIGNAL_VOCAB)))
    generic_hits = sum(1 for verb in _GENERIC_ACTION_VERBS if lowered.startswith(f"{verb} ") or f" {verb} " in lowered)
    if len(tokens) <= 3 and generic_hits:
        return True
    if generic_hits and strong_hits == 0:
        return True
    if generic_hits >= 2 and strong_hits < 2:
        return True
    if generic_hits and strong_hits < 2 and len(tokens) <= 8:
        return True
    return False


def bind_action_to_evidence(
    *,
    step: int,
    text: str,
    reason: str,
    evidence: list[str],
) -> GroundedActionStep | None:
    action_text = _finalize_action_text(text) or _normalize_text(text)
    if not action_text:
        return None
    evidence_rows: list[str] = []
    seen: set[str] = set()
    for raw in evidence:
        normalized = _normalize_text(raw)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        evidence_rows.append(normalized)
        if len(evidence_rows) >= 4:
            break
    return GroundedActionStep(
        step=step,
        text=action_text,
        reason=_normalize_text(reason),
        evidence=evidence_rows,
    )


def _action_step_evidence(
    query_context: dict[str, Any],
    *,
    primary: EvidenceCandidate,
    support: list[EvidenceCandidate],
    probable_root_cause: str | None,
    matched_terms: list[str],
) -> list[str]:
    evidence = [_evidence_reference_label(primary)]
    evidence.extend(_evidence_reference_label(candidate) for candidate in support[1:3])
    for term in matched_terms[:2]:
        evidence.append(f"signal: {term}")
    if probable_root_cause:
        evidence.append(f"root cause: {_truncate(probable_root_cause, limit=100)}")
    return evidence[:4]


def _step_reason(
    *,
    primary: EvidenceCandidate,
    matched_terms: list[str],
    probable_root_cause: str | None,
    fallback: str,
) -> str:
    terms = ", ".join(matched_terms[:3])
    if probable_root_cause and terms:
        return f"{primary.reference} aligns on {terms}, and the likely cause points to {probable_root_cause}."
    if terms:
        return f"{primary.reference} matches the same {terms} pattern."
    if probable_root_cause:
        return f"{primary.reference} supports the same failure path, and the likely cause points to {probable_root_cause}."
    return fallback


def _dedupe_action_steps(action_steps: list[GroundedActionStep], *, query_context: dict[str, Any], limit: int = 3) -> list[GroundedActionStep]:
    deduped: list[GroundedActionStep] = []
    seen: set[str] = set()
    for candidate in action_steps:
        normalized = _finalize_action_text(candidate.text) or _normalize_text(candidate.text)
        key = normalized.casefold()
        if not normalized or key in seen or action_is_too_generic(normalized, query_context):
            continue
        seen.add(key)
        deduped.append(
            GroundedActionStep(
                step=len(deduped) + 1,
                text=normalized,
                reason=candidate.reason,
                evidence=candidate.evidence,
            )
        )
        if len(deduped) >= limit:
            break
    return deduped


def build_grounded_actions(
    query_context: dict[str, Any],
    *,
    primary: EvidenceCandidate,
    support: list[EvidenceCandidate],
    probable_root_cause: str | None,
    lang: str,
    tentative: bool = False,
) -> list[GroundedActionStep]:
    signals = extract_ticket_operational_signals(
        query_context,
        primary=primary,
        support=support,
        probable_root_cause=probable_root_cause,
    )
    preferred_family = _preferred_signal_topic(signals)
    matched_terms = list(signals.get("matched_terms") or [])
    subject = str(signals.get("subject") or "affected workflow").strip()
    evidence_rows = _action_step_evidence(
        query_context,
        primary=primary,
        support=support,
        probable_root_cause=probable_root_cause,
        matched_terms=matched_terms,
    )
    default_reason = _step_reason(
        primary=primary,
        matched_terms=matched_terms,
        probable_root_cause=probable_root_cause,
        fallback=f"{primary.reference} is the strongest aligned evidence item for this ticket.",
    )
    action_steps: list[GroundedActionStep] = []

    primary_action = _finalize_action_text(primary.action_text or "")
    primary_action_is_strong = (
        primary.relevance >= 0.32
        or primary.context_score >= 0.28
        or primary.exact_focus_hits >= 2
        or primary.exact_strong_hits >= 1
        or primary.strong_overlap >= 0.18
    )
    if not tentative and primary_action and primary_action_is_strong and not action_is_too_generic(primary_action, query_context):
        bound = bind_action_to_evidence(
            step=1,
            text=primary_action,
            reason=default_reason,
            evidence=evidence_rows,
        )
        if bound is not None:
            action_steps.append(bound)

    template_seed_supported = bool(
        preferred_family
        and (
            primary.exact_focus_hits >= 1
            or primary.exact_strong_hits >= 1
            or primary.strong_overlap >= ADVISOR_CAUSE_CONFIRMATION["supported_excerpt_overlap"]
            or primary.relevance >= ADVISOR_CAUSE_CONFIRMATION["supported_excerpt_relevance"]
            or primary.context_score >= ADVISOR_CAUSE_CONFIRMATION["supported_excerpt_context_strong"]
            or len(matched_terms) >= 2
            or any(
                candidate.reference != primary.reference
                and candidate.cluster_id == primary.cluster_id
                and not candidate.topic_mismatch
                and not candidate.domain_mismatch
                for candidate in support[1:]
            )
            or (
                primary.evidence_type != "KB article"
                and not primary.domain_mismatch
                and not primary.topic_mismatch
                and primary.score >= 0.72
            )
            or (
                preferred_family in list(query_context.get("topics") or [])
                and primary.evidence_type != "KB article"
                and not primary.concrete
                and not primary.topic_mismatch
            )
        )
    )
    template_texts = topic_grounded_action_templates(preferred_family, lang=lang) if template_seed_supported else []
    template_reasons = topic_grounded_action_reasons(preferred_family, lang=lang) if template_seed_supported else []
    if template_texts:
        for index, text in enumerate(template_texts):
            reason = template_reasons[index] if index < len(template_reasons) and template_reasons[index] else default_reason
            bound = bind_action_to_evidence(step=len(action_steps) + 1, text=text, reason=reason, evidence=evidence_rows)
            if bound is not None:
                action_steps.append(bound)
    elif (
        not action_steps
        and subject
        and any(query_context.get(key) for key in ("strong_terms", "topics", "domains"))
        and (template_seed_supported or primary.evidence_type != "KB article")
    ):
        fallback_text = (
            f"Verify the failing {subject} path against one affected case before applying a broader change."
            if lang == "en"
            else f"Verifiez le chemin {subject} en echec sur un cas affecte avant d'appliquer un changement plus large."
        )
        bound = bind_action_to_evidence(step=1, text=fallback_text, reason=default_reason, evidence=evidence_rows)
        if bound is not None:
            action_steps.append(bound)

    return _dedupe_action_steps(action_steps, query_context=query_context)


def build_validation_from_actions(
    query_context: dict[str, Any],
    *,
    action_steps: list[GroundedActionStep],
    lang: str,
) -> list[str]:
    if not action_steps:
        return []
    action_text = " ".join(step.text for step in action_steps)
    action_tokens = _meaningful_tokens(action_text)
    query_tokens = set(_ordered_query_terms(query_context))
    combined_tokens = action_tokens.union(query_tokens)
    for topic in ("crm_integration", "notification_distribution", "payroll_export", "mail_transport", "network_access"):
        if combined_tokens.intersection(set(_TOPIC_HINTS.get(topic) or [])):
            topic_steps = topic_validation_actions(topic, lang=lang)
            if topic_steps:
                return topic_steps
    return [
        (
            "Validate the corrected workflow on one affected case before broader rollout."
            if lang == "en"
            else "Validez le flux corrige sur un cas affecte avant un deploiement plus large."
        ),
    ]


def _serialize_action_steps(action_steps: list[GroundedActionStep]) -> list[dict[str, Any]]:
    return [
        {
            "step": step.step,
            "text": step.text,
            "reason": step.reason,
            "evidence": list(step.evidence),
        }
        for step in action_steps
    ]


def _joined_match_terms(query_context: dict[str, Any], candidate: EvidenceCandidate) -> str:
    terms = _match_terms(query_context, candidate.title or "", candidate.excerpt, candidate.action_text or "", candidate.reference)
    return ", ".join(terms[:3])


def _evidence_why_relevant(
    query_context: dict[str, Any],
    candidate: EvidenceCandidate,
    *,
    primary_action: str | None,
    lang: str,
) -> str:
    matched_terms = _joined_match_terms(query_context, candidate)
    if candidate.evidence_type == "related problem":
        if lang == "fr":
            return (
                f"Meme pattern de cause racine sur {matched_terms}."
                if matched_terms
                else "Meme pattern de cause racine documente."
            )
        return (
            f"Same documented root-cause pattern around {matched_terms}."
            if matched_terms
            else "Same documented root-cause pattern."
        )
    if candidate.action_text and primary_action and _texts_agree(candidate.action_text, primary_action):
        if lang == "fr":
            return (
                f"Meme symptome et meme chemin de resolution sur {matched_terms}."
                if matched_terms
                else "Meme symptome et meme chemin de resolution."
            )
        return (
            f"Same symptom and same fix pattern on {matched_terms}."
            if matched_terms
            else "Same symptom and same fix pattern."
        )
    if lang == "fr":
        return f"Recoupe le ticket sur {matched_terms}." if matched_terms else "Recoupe le ticket sur les memes signaux."
    return f"Overlaps with the ticket on {matched_terms}." if matched_terms else "Overlaps with the same ticket signals."


def _build_evidence_sources(
    query_context: dict[str, Any],
    support: list[EvidenceCandidate],
    *,
    primary_action: str | None,
    lang: str,
    root_problem_ref: str | None = None,
    root_cause: str | None = None,
) -> list[dict[str, Any]]:
    evidence_sources: list[dict[str, Any]] = []
    for item in support[:3]:
        evidence_sources.append(
            {
                "evidence_type": item.evidence_type,
                "reference": item.reference,
                "source_id": item.source_id,
                "title": item.title,
                "excerpt": item.excerpt,
                "relevance": round(max(0.0, min(1.0, item.relevance)), 4),
                "why_relevant": _evidence_why_relevant(query_context, item, primary_action=primary_action, lang=lang),
            }
        )
    if root_problem_ref and all(row["reference"] != root_problem_ref for row in evidence_sources):
        evidence_sources.append(
            {
                "evidence_type": "related problem",
                "reference": root_problem_ref,
                "source_id": root_problem_ref,
                "title": root_problem_ref,
                "excerpt": root_cause or "",
                "relevance": 0.6,
                "why_relevant": (
                    "Cause racine documentee sur le probleme lie."
                    if lang == "fr"
                    else "Documents the linked root cause directly."
                ),
            }
        )
    return evidence_sources[:3]


def build_match_explanation(
    query_context: dict[str, Any],
    *,
    primary: EvidenceCandidate,
    support: list[EvidenceCandidate],
    root_problem_ref: str | None,
    root_cause: str | None,
    lang: str,
) -> list[str]:
    explanations: list[str] = []
    matched_terms = _joined_match_terms(query_context, primary)
    subject = matched_terms or _subject_label(query_context)
    if subject:
        explanations.append(
            (
                f"Le ticket courant montre des signaux sur {subject}."
                if lang == "fr"
                else f"The current ticket shows signals around {subject}."
            )
        )
    primary_subject = primary.title or primary.reference
    explanations.append(
        (
            f"{primary.evidence_type.capitalize()} {primary_subject} recoupe le meme composant ou symptome."
            if lang == "fr"
            else f"{primary.evidence_type.capitalize()} {primary_subject} overlaps with the same component or symptom."
        )
    )
    agreeing_refs = [item.reference for item in support[1:] if item.action_text and primary.action_text and _texts_agree(item.action_text, primary.action_text)]
    if agreeing_refs:
        refs = ", ".join(agreeing_refs[:2])
        explanations.append(
            (
                f"Le meme chemin de resolution est confirme par {refs}."
                if lang == "fr"
                else f"The same fix pattern is confirmed by {refs}."
            )
        )
    if root_problem_ref and root_cause:
        explanations.append(
            (
                f"{root_problem_ref} documente la cause racine: {root_cause}"
                if lang == "fr"
                else f"{root_problem_ref} documents the root cause: {root_cause}"
            )
        )
    deduped: list[str] = []
    seen: set[str] = set()
    for item in explanations:
        normalized = _normalize_text(item)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
        if len(deduped) >= 4:
            break
    return deduped


def is_action_relevant_to_ticket(query_context: dict[str, Any], action_text: str) -> float:
    normalized_action = _finalize_action_text(action_text) or _normalize_text(action_text)
    action_tokens = _meaningful_tokens(normalized_action)
    if not action_tokens:
        return 0.0

    query_tokens = set(query_context.get("tokens") or [])
    title_tokens = set(query_context.get("title_tokens") or [])
    focus_terms = set(query_context.get("focus_terms") or [])
    strong_terms = set(query_context.get("strong_terms") or [])
    description_tokens = query_tokens.difference(title_tokens)
    key_terms = focus_terms or title_tokens or query_tokens
    metadata = dict(query_context.get("metadata") or {})

    title_overlap = _overlap_score(title_tokens, action_tokens)
    description_overlap = _overlap_score(description_tokens or query_tokens, action_tokens)
    entity_overlap = _overlap_score(focus_terms, action_tokens)
    noun_overlap = _overlap_score(key_terms, action_tokens)
    key_hits = len(key_terms.intersection(action_tokens))
    strong_overlap = _overlap_score(strong_terms or key_terms, action_tokens)
    strong_hits = len(strong_terms.intersection(action_tokens))

    query_domains = set(query_context.get("domains") or [])
    query_topics = set(query_context.get("topics") or [])
    category_tokens = _meaningful_tokens(str(metadata.get("category") or "").replace("_", " "))
    action_domains = _domain_signals(action_tokens)
    action_topics = _topic_signals(action_tokens)
    domain_match = bool(query_domains and action_domains and not query_domains.isdisjoint(action_domains))
    category_match = bool(category_tokens.intersection(action_tokens))
    domain_mismatch = bool(query_domains and action_domains and query_domains.isdisjoint(action_domains))
    topic_overlap = (
        len(query_topics.intersection(action_topics)) / max(1, len(query_topics))
        if query_topics and action_topics
        else 0.0
    )
    topic_mismatch = bool(query_topics and action_topics and query_topics.isdisjoint(action_topics))

    score = (
        (ADVISOR_RELEVANCE_WEIGHTS["title_overlap"] * title_overlap)
        + (ADVISOR_RELEVANCE_WEIGHTS["description_overlap"] * description_overlap)
        + (ADVISOR_RELEVANCE_WEIGHTS["entity_overlap"] * entity_overlap)
        + (ADVISOR_RELEVANCE_WEIGHTS["noun_overlap"] * noun_overlap)
        + (ADVISOR_RELEVANCE_WEIGHTS["strong_overlap"] * strong_overlap)
        + (ADVISOR_RELEVANCE_WEIGHTS["topic_overlap"] * topic_overlap)
        + min(ADVISOR_RELEVANCE_WEIGHTS["key_hit_cap"], key_hits * ADVISOR_RELEVANCE_WEIGHTS["key_hit_step"])
        + min(ADVISOR_RELEVANCE_WEIGHTS["strong_hit_cap"], strong_hits * ADVISOR_RELEVANCE_WEIGHTS["strong_hit_step"])
    )
    if domain_match or category_match:
        score += ADVISOR_RELEVANCE_WEIGHTS["domain_or_category_bonus"]
    if topic_mismatch:
        score -= ADVISOR_RELEVANCE_WEIGHTS["topic_mismatch_penalty"]
    if domain_mismatch:
        score -= ADVISOR_RELEVANCE_WEIGHTS["domain_mismatch_penalty"]
    if strong_hits == 0 and key_hits == 0 and title_overlap < 0.08 and entity_overlap < 0.08:
        score = min(score, ADVISOR_RELEVANCE_WEIGHTS["weak_signal_cap"])
    if topic_mismatch and strong_hits == 0:
        score = min(score, ADVISOR_RELEVANCE_WEIGHTS["topic_cap"])
    return round(max(0.0, min(1.0, score)), 4)


def _confidence_band(value: float) -> str:
    return confidence_band(value)


def classify_confidence(value: float) -> str:
    return _confidence_band(value)


def enforce_action_alignment(
    query_context: dict[str, Any],
    *,
    primary: EvidenceCandidate,
    support: list[EvidenceCandidate],
    recommended_action: str | None,
    agreement_count: int,
) -> dict[str, Any]:
    action_text = _finalize_action_text(recommended_action or "") or _normalize_text(recommended_action)
    has_query_signals = any(query_context.get(key) for key in ("tokens", "title_tokens", "focus_terms", "strong_terms"))
    action_relevance_score = is_action_relevant_to_ticket(query_context, action_text) if action_text else 0.0
    if not has_query_signals and action_text:
        action_relevance_score = round(
            max(
                action_relevance_score,
                min(
                    ADVISOR_ACTION_ALIGNMENT_WEIGHTS["score_cap"],
                    (primary.relevance * ADVISOR_ACTION_ALIGNMENT_WEIGHTS["relevance_weight"])
                    + (_actionability_score(action_text) * ADVISOR_ACTION_ALIGNMENT_WEIGHTS["actionability_weight"])
                    + (min(1.0, primary.score) * ADVISOR_ACTION_ALIGNMENT_WEIGHTS["primary_score_weight"]),
                ),
            ),
            4,
        )

    symptom_match = bool(
        primary.exact_focus_hits >= 1
        or primary.lexical_overlap >= 0.16
        or primary.strong_overlap >= 0.16
        or primary.exact_strong_hits >= 1
        or (
            not primary.domain_mismatch
            and not primary.topic_mismatch
            and action_relevance_score >= ADVISOR_ALIGNMENT_THRESHOLDS["hard_action_relevance"]
        )
        or (not has_query_signals and (primary.relevance >= ADVISOR_ALIGNMENT_THRESHOLDS["action_relevance"] or primary.score >= 0.72))
    )
    component_match = bool(
        not primary.domain_mismatch
        and not primary.topic_mismatch
        and (
            primary.exact_strong_hits >= 1
            or primary.strong_overlap >= 0.12
            or primary.exact_focus_hits >= 1
            or action_relevance_score >= ADVISOR_ALIGNMENT_THRESHOLDS["action_relevance"]
            or not has_query_signals
        )
    )
    resolution_pattern_match = bool(
        action_text
        and (
            (
                action_relevance_score >= 0.24
                and (_actionability_score(action_text) >= ADVISOR_ALIGNMENT_THRESHOLDS["hard_action_relevance"] or agreement_count >= 2 or len(support) >= 2)
            )
            or (
                not has_query_signals
                and _actionability_score(action_text) >= ADVISOR_ALIGNMENT_THRESHOLDS["hard_action_relevance"]
                and (primary.concrete or agreement_count >= 1)
            )
        )
    )
    safe_for_action = symptom_match and component_match and resolution_pattern_match
    downgrade_to_tentative = (
        symptom_match
        and component_match
        and action_relevance_score >= ADVISOR_ALIGNMENT_THRESHOLDS["hard_action_relevance"]
    ) and not safe_for_action
    return {
        "action_relevance_score": round(max(0.0, min(1.0, action_relevance_score)), 4),
        "symptom_match": symptom_match,
        "component_match": component_match,
        "resolution_pattern_match": resolution_pattern_match,
        "safe_for_action": safe_for_action,
        "downgrade_to_tentative": downgrade_to_tentative,
    }


def _action_step_text(action: str) -> str:
    cleaned = _normalize_text(str(action or ""))
    cleaned = re.sub(r"(?i)^tentative:\s*", "", cleaned).strip()
    return cleaned


def _validation_step(query_context: dict[str, Any], *, lang: str) -> str:
    tokens = set(_ordered_query_terms(query_context))
    preferred_topic = _preferred_query_topic(query_context)
    if preferred_topic:
        step = topic_validation_step(preferred_topic, lang=lang)
        if step:
            return step
    for topic in ("crm_integration", "auth_path", "network_access", "payroll_export", "mail_transport", "notification_distribution"):
        if tokens.intersection(set(_TOPIC_HINTS.get(topic) or [])):
            step = topic_validation_step(topic, lang=lang)
            if step:
                return step
    if tokens.intersection({"printer", "keyboard", "dock", "device", "hardware"}):
        return (
            "Validez l'etat du poste ou du peripherique avec le demandeur avant cloture."
            if lang == "fr"
            else "Validate the device state with the requester before closure."
        )
    return (
        "Validez le resultat sur un utilisateur affecte ou un ticket lie avant cloture."
        if lang == "fr"
        else "Validate the outcome on an affected user or linked ticket before closure."
    )


def build_validation_steps(
    query_context: dict[str, Any],
    *,
    recommended_action: str | None,
    supporting_context: str | None,
    lang: str,
) -> list[str]:
    steps = []
    subject = _subject_label(query_context)
    if recommended_action:
        steps.append(
            (
                f"Verifiez que l'action '{_truncate(recommended_action, limit=96)}' retablit bien le flux attendu."
                if lang == "fr"
                else f"Verify that '{_truncate(recommended_action, limit=96)}' restores the expected workflow."
            )
        )
    steps.append(_validation_step(query_context, lang=lang))
    if supporting_context:
        steps.append(
            (
                f"Confirmez aussi le contexte annexe: {_truncate(supporting_context, limit=120)}"
                if lang == "fr"
                else f"Also confirm the surrounding context: {_truncate(supporting_context, limit=120)}"
            )
        )
    elif subject:
        steps.append(
            (
                f"Controlez le perimetre {subject} avec un cas affecte representatif."
                if lang == "fr"
                else f"Check the {subject} path with a representative affected case."
            )
        )
    deduped: list[str] = []
    seen: set[str] = set()
    for item in steps:
        normalized = _normalize_text(item)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
        if len(deduped) >= 3:
            break
    return deduped


def build_fallback_action(
    query_context: dict[str, Any],
    *,
    probable_root_cause: str | None,
    supporting_context: str | None,
    lang: str,
) -> str | None:
    fallback = _safe_diagnostic_action(query_context, lang=lang)
    if fallback:
        return fallback
    if probable_root_cause:
        return (
            f"Si le probleme persiste, verifiez ensuite la cause probable: {_truncate(probable_root_cause, limit=120)}."
            if lang == "fr"
            else f"If the issue persists, verify the probable root cause next: {_truncate(probable_root_cause, limit=120)}."
        )
    if supporting_context:
        return (
            f"Si le probleme persiste, controlez ensuite ce contexte: {_truncate(supporting_context, limit=120)}."
            if lang == "fr"
            else f"If the issue persists, check this surrounding context next: {_truncate(supporting_context, limit=120)}."
        )
    subject = _subject_label(query_context)
    if subject:
        return (
            f"Capturez un signal d'echec actuel sur un cas affecte representatif du perimetre {subject}, puis verifiez ce cas avant toute correction plus large."
            if lang == "fr"
            else f"Capture one current failure signal on a representative affected {subject} path, then verify that case before broader remediation."
        )
    return (
        "Capturez un journal, une erreur ou un exemple d'echec actuel sur un cas affecte avant toute correction plus large."
        if lang == "fr"
        else "Capture one current log, error, or failing example on an affected case before broader remediation."
    )


def _next_best_actions(
    *,
    recommended_action: str,
    probable_root_cause: str | None,
    tentative: bool,
    query_context: dict[str, Any],
    support: list[EvidenceCandidate],
    lang: str,
) -> list[str]:
    steps: list[str] = []
    first_step = _action_step_text(recommended_action)
    if first_step:
        steps.append(first_step)

    if tentative:
        reference = support[0].reference if support else ""
        cautious_step = (
            f"Confirmez d'abord que les symptomes actuels correspondent a {reference} avant de generaliser ce correctif."
            if lang == "fr"
            else f"Confirm the current symptoms match {reference} before rolling out this fix more broadly."
        )
        steps.append(cautious_step if reference else _validation_step(query_context, lang=lang))
    elif probable_root_cause:
        root = _truncate(probable_root_cause, limit=120)
        steps.append(
            f"Verifiez la cause probable: {root}."
            if lang == "fr"
            else f"Verify the probable root cause: {root}."
        )

    steps.append(_validation_step(query_context, lang=lang))
    steps.append(
        "Documentez l'evidence retenue et mettez a jour la resolution avant cloture."
        if lang == "fr"
        else "Document the supporting evidence and update the resolution before closure."
    )

    deduped: list[str] = []
    seen: set[str] = set()
    for raw in steps:
        cleaned = _finalize_action_text(raw) or _normalize_text(raw)
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
        if len(deduped) >= 4:
            break
    return deduped


def _parse_datetime(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.timezone.utc) if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    text = _normalize_text(value)
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(dt.timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _incident_cluster(
    retrieval: dict[str, Any],
    query_context: dict[str, Any],
    *,
    lang: str,
    selected_cluster_id: str | None = None,
) -> dict[str, Any] | None:
    now = dt.datetime.now(dt.timezone.utc)
    recent: list[dict[str, Any]] = []
    for row in list(retrieval.get("similar_tickets") or []):
        row_cluster_id = str(row.get("cluster_id") or "").strip().lower()
        if selected_cluster_id and row_cluster_id and row_cluster_id != str(selected_cluster_id).strip().lower():
            continue
        if bool(row.get("domain_mismatch")) or bool(row.get("topic_mismatch")):
            continue
        context_score = float(row.get("context_score") or 0.0)
        lexical_overlap = float(row.get("lexical_overlap") or 0.0)
        if context_score < 0.18 and lexical_overlap < 0.12:
            continue
        updated_at = _parse_datetime(row.get("updated_at") or row.get("created_at"))
        if updated_at is None or (now - updated_at) > dt.timedelta(hours=24):
            continue
        recent.append(row)
    if len(recent) < 2:
        return None
    terms = _match_terms(
        query_context,
        *(str(row.get("title") or "") for row in recent),
        *(str(row.get("resolution_snippet") or "") for row in recent),
    )
    subject = ", ".join(terms[:3]) if terms else ", ".join(_display_term(token) for token in _ordered_query_terms(query_context)[:3])
    if lang == "fr":
        summary = f"Grappe potentielle: {len(recent)} tickets similaires sur {subject} au cours des 24 dernieres heures."
    else:
        summary = f"Potential incident cluster: {len(recent)} similar tickets on {subject} in the last 24 hours."
    return {"count": len(recent), "window_hours": 24, "summary": summary}


def _impact_summary(query_context: dict[str, Any], *, lang: str, cluster: dict[str, Any] | None) -> str | None:
    terms = [_display_term(token) for token in _ordered_query_terms(query_context)[:4]]
    if not terms:
        return None
    subject = ", ".join(terms[:3])
    if lang == "fr":
        summary = f"Impact potentiel: ce ticket semble affecter le flux {subject}."
        if cluster:
            summary += " Plusieurs tickets similaires suggerent un impact partage."
        return summary
    summary = f"Potential service impact: this issue appears to affect the {subject} flow."
    if cluster:
        summary += " Multiple similar tickets suggest shared impact."
    return summary


def _extract_root_cause_text(*texts: str) -> str | None:
    for raw in texts:
        normalized = _normalize_text(raw)
        if not normalized:
            continue
        for pattern in _ROOT_CAUSE_PATTERNS:
            match = pattern.search(normalized)
            if match:
                captured = _truncate(match.group(1), limit=160)
                if captured:
                    return captured
    return None


def _best_from_bucket(rows: list[EvidenceCandidate]) -> list[EvidenceCandidate]:
    return sorted(
        rows,
        key=lambda item: (
            1 if not item.topic_mismatch else 0,
            1 if not item.domain_mismatch else 0,
            item.score,
            item.coherence_score,
            item.strong_overlap,
            item.exact_strong_hits,
            item.context_score,
            item.relevance,
            item.concrete,
        ),
        reverse=True,
    )


def _candidate_from_similar_ticket(row: dict[str, Any], *, query_context: dict[str, Any]) -> EvidenceCandidate | None:
    raw_excerpt = str(row.get("resolution_snippet") or row.get("evidence_snippet") or "")
    excerpt = _truncate(raw_excerpt)
    if not excerpt:
        return None
    reference = str(row.get("jira_key") or row.get("id") or "").strip()
    if not reference:
        return None
    relevance, metrics = _candidate_relevance(
        excerpt=excerpt,
        reference=reference,
        row=row,
        query_context=query_context,
    )
    action_text = _extract_fix_sentence(raw_excerpt, query_context=query_context)
    cluster_id, coherence_score = _candidate_cluster_metadata(
        query_context=query_context,
        reference=reference,
        title=_normalize_text(row.get("title") or row.get("summary")) or reference,
        text=raw_excerpt,
        category_hint=str(row.get("category") or ""),
        action_text=action_text,
        evidence_type="resolved ticket" if str(row.get("status") or "").lower() in {"resolved", "closed"} else "similar ticket",
        base_score=float(row.get("similarity_score") or 0.0),
        metrics=metrics,
        row=row,
    )
    return EvidenceCandidate(
        evidence_type="resolved ticket" if str(row.get("status") or "").lower() in {"resolved", "closed"} else "similar ticket",
        reference=reference,
        excerpt=excerpt,
        source_id=reference,
        title=_normalize_text(row.get("title") or row.get("summary")) or reference,
        score=float(row.get("similarity_score") or 0.0),
        concrete=bool(action_text) or _is_concrete_fix(excerpt),
        relevance=relevance,
        lexical_overlap=float(metrics["lexical_overlap"]),
        exact_focus_hits=int(metrics["exact_focus_hits"]),
        strong_overlap=float(metrics["strong_overlap"]),
        exact_strong_hits=int(metrics["exact_strong_hits"]),
        domain_mismatch=bool(metrics["domain_mismatch"]),
        topic_mismatch=bool(metrics["topic_mismatch"]),
        action_text=action_text,
        context_score=float(metrics["context_score"]),
        title_overlap=float(metrics["title_overlap"]),
        topic_overlap=float(metrics["topic_overlap"]),
        cluster_id=cluster_id,
        coherence_score=coherence_score,
    )


def _candidate_from_kb(row: dict[str, Any], *, query_context: dict[str, Any]) -> EvidenceCandidate | None:
    raw_excerpt = str(row.get("excerpt") or "")
    excerpt = _truncate(raw_excerpt)
    if not excerpt:
        return None
    reference = str(row.get("id") or row.get("title") or "").strip()
    if not reference:
        return None
    relevance, metrics = _candidate_relevance(
        excerpt=excerpt,
        reference=reference,
        row=row,
        query_context=query_context,
    )
    action_text = _extract_fix_sentence(raw_excerpt, query_context=query_context)
    cluster_id, coherence_score = _candidate_cluster_metadata(
        query_context=query_context,
        reference=reference,
        title=_normalize_text(row.get("title")) or reference,
        text=raw_excerpt,
        category_hint=str(row.get("category") or ""),
        action_text=action_text,
        evidence_type="KB article",
        base_score=float(row.get("similarity_score") or 0.0),
        metrics=metrics,
        row=row,
    )
    return EvidenceCandidate(
        evidence_type="KB article",
        reference=reference,
        excerpt=excerpt,
        source_id=str(row.get("id") or reference).strip() or reference,
        title=_normalize_text(row.get("title")) or reference,
        score=float(row.get("similarity_score") or 0.0),
        concrete=bool(action_text) or _is_concrete_fix(excerpt),
        relevance=relevance,
        lexical_overlap=float(metrics["lexical_overlap"]),
        exact_focus_hits=int(metrics["exact_focus_hits"]),
        strong_overlap=float(metrics["strong_overlap"]),
        exact_strong_hits=int(metrics["exact_strong_hits"]),
        domain_mismatch=bool(metrics["domain_mismatch"]),
        topic_mismatch=bool(metrics["topic_mismatch"]),
        action_text=action_text,
        context_score=float(metrics["context_score"]),
        title_overlap=float(metrics["title_overlap"]),
        topic_overlap=float(metrics["topic_overlap"]),
        cluster_id=cluster_id,
        coherence_score=coherence_score,
    )


def _candidate_from_comment(row: dict[str, Any], *, query_context: dict[str, Any]) -> EvidenceCandidate | None:
    raw_excerpt = str(row.get("text") or row.get("content") or "")
    excerpt = _truncate(raw_excerpt, limit=260)
    if not excerpt:
        return None
    reference = str(row.get("source_id") or row.get("jira_key") or row.get("id") or "").strip()
    if not reference:
        reference = "comment"
    score = max(float(row.get("confidence") or 0.0), float(row.get("quality_score") or 0.0))
    relevance, metrics = _candidate_relevance(
        excerpt=excerpt,
        reference=reference,
        row=row,
        query_context=query_context,
    )
    action_text = _extract_fix_sentence(raw_excerpt, query_context=query_context)
    cluster_id, coherence_score = _candidate_cluster_metadata(
        query_context=query_context,
        reference=reference,
        title=_normalize_text(row.get("title") or row.get("ticket_id") or f"Comment {reference}") or f"Comment {reference}",
        text=raw_excerpt,
        category_hint=str(row.get("category") or ""),
        action_text=action_text,
        evidence_type="comment",
        base_score=score,
        metrics=metrics,
        row=row,
    )
    return EvidenceCandidate(
        evidence_type="comment",
        reference=reference,
        excerpt=excerpt,
        source_id=reference,
        title=_normalize_text(row.get("title") or row.get("ticket_id") or f"Comment {reference}") or f"Comment {reference}",
        score=score,
        concrete=bool(action_text) or _is_concrete_fix(excerpt),
        relevance=relevance,
        lexical_overlap=float(metrics["lexical_overlap"]),
        exact_focus_hits=int(metrics["exact_focus_hits"]),
        strong_overlap=float(metrics["strong_overlap"]),
        exact_strong_hits=int(metrics["exact_strong_hits"]),
        domain_mismatch=bool(metrics["domain_mismatch"]),
        topic_mismatch=bool(metrics["topic_mismatch"]),
        action_text=action_text,
        context_score=float(metrics["context_score"]),
        title_overlap=float(metrics["title_overlap"]),
        topic_overlap=float(metrics["topic_overlap"]),
        cluster_id=cluster_id,
        coherence_score=coherence_score,
    )


def _candidate_from_problem(row: dict[str, Any], *, query_context: dict[str, Any]) -> EvidenceCandidate | None:
    raw_excerpt = str(row.get("root_cause") or row.get("match_reason") or "")
    excerpt = _truncate(raw_excerpt)
    if not excerpt:
        return None
    reference = str(row.get("id") or row.get("title") or "").strip()
    if not reference:
        return None
    relevance, metrics = _candidate_relevance(
        excerpt=excerpt,
        reference=reference,
        row=row,
        query_context=query_context,
    )
    cluster_id, coherence_score = _candidate_cluster_metadata(
        query_context=query_context,
        reference=reference,
        title=_normalize_text(row.get("title")) or reference,
        text=raw_excerpt,
        category_hint=str(row.get("category") or ""),
        action_text=None,
        evidence_type="related problem",
        base_score=float(row.get("similarity_score") or 0.0),
        metrics=metrics,
        row=row,
    )
    return EvidenceCandidate(
        evidence_type="related problem",
        reference=reference,
        excerpt=excerpt,
        source_id=reference,
        title=_normalize_text(row.get("title")) or reference,
        score=float(row.get("similarity_score") or 0.0),
        concrete=False,
        relevance=relevance,
        lexical_overlap=float(metrics["lexical_overlap"]),
        exact_focus_hits=int(metrics["exact_focus_hits"]),
        strong_overlap=float(metrics["strong_overlap"]),
        exact_strong_hits=int(metrics["exact_strong_hits"]),
        domain_mismatch=bool(metrics["domain_mismatch"]),
        topic_mismatch=bool(metrics["topic_mismatch"]),
        action_text=None,
        context_score=float(metrics["context_score"]),
        title_overlap=float(metrics["title_overlap"]),
        topic_overlap=float(metrics["topic_overlap"]),
        cluster_id=cluster_id,
        coherence_score=coherence_score,
    )


def _annotate_related_problem_row(row: dict[str, Any], candidate: EvidenceCandidate) -> None:
    row["_advisor_cluster_id"] = candidate.cluster_id
    row["_advisor_relevance"] = round(float(candidate.relevance), 4)
    row["_advisor_exact_focus_hits"] = int(candidate.exact_focus_hits)
    row["_advisor_exact_strong_hits"] = int(candidate.exact_strong_hits)


def _build_buckets(retrieval: dict[str, Any], *, query_context: dict[str, Any]) -> list[list[EvidenceCandidate]]:
    resolved: list[EvidenceCandidate] = []
    similar: list[EvidenceCandidate] = []
    kb_rows: list[EvidenceCandidate] = []
    comment_rows: list[EvidenceCandidate] = []
    problem_rows: list[EvidenceCandidate] = []

    for row in list(retrieval.get("similar_tickets") or []):
        candidate = _candidate_from_similar_ticket(row, query_context=query_context)
        if candidate is None:
            continue
        if candidate.evidence_type == "resolved ticket":
            resolved.append(candidate)
        else:
            similar.append(candidate)

    for row in list(retrieval.get("kb_articles") or []):
        candidate = _candidate_from_kb(row, query_context=query_context)
        if candidate is not None:
            kb_rows.append(candidate)

    source_comments = list(retrieval.get("solution_recommendations") or []) or list(retrieval.get("comment_matches") or [])
    for row in source_comments:
        candidate = _candidate_from_comment(row, query_context=query_context)
        if candidate is not None:
            comment_rows.append(candidate)

    for row in list(retrieval.get("related_problems") or []):
        candidate = _candidate_from_problem(row, query_context=query_context)
        if candidate is not None:
            _annotate_related_problem_row(row, candidate)
            problem_rows.append(candidate)

    return [
        _best_from_bucket(resolved),
        _best_from_bucket(similar),
        _best_from_bucket(kb_rows),
        _best_from_bucket(comment_rows),
        _best_from_bucket(problem_rows),
    ]


def _passes_relevance_gate(candidate: EvidenceCandidate, *, allow_weak: bool = False) -> bool:
    if candidate.topic_mismatch and candidate.exact_focus_hits == 0 and candidate.exact_strong_hits == 0 and candidate.strong_overlap < 0.12:
        return False
    if (
        candidate.domain_mismatch
        and candidate.exact_focus_hits == 0
        and candidate.strong_overlap < 0.12
        and candidate.relevance < ADVISOR_ALIGNMENT_THRESHOLDS["action_relevance"]
    ):
        return False
    if candidate.relevance >= 0.24 and not candidate.topic_mismatch:
        return True
    if candidate.exact_focus_hits >= 2 and candidate.exact_strong_hits >= 1 and not candidate.domain_mismatch and not candidate.topic_mismatch:
        return True
    if candidate.exact_strong_hits >= 2 and not candidate.topic_mismatch:
        return True
    if allow_weak and candidate.relevance >= 0.12 and not candidate.domain_mismatch and not candidate.topic_mismatch:
        return True
    return False


def _flatten_candidates(buckets: list[list[EvidenceCandidate]]) -> list[EvidenceCandidate]:
    return [candidate for bucket in buckets for candidate in bucket]


def _candidate_cluster_inputs(candidates: list[EvidenceCandidate]) -> list[dict[str, Any]]:
    return [
        {
            "reference": candidate.reference,
            "title": candidate.title,
            "text": candidate.excerpt,
            "action_text": candidate.action_text,
            "evidence_type": candidate.evidence_type,
            "base_score": candidate.score,
            "cluster_id": candidate.cluster_id,
            "coherence_score": candidate.coherence_score,
            "topic_mismatch": candidate.topic_mismatch,
            "domain_mismatch": candidate.domain_mismatch,
            "metrics": {
                "context_score": candidate.context_score,
                "lexical_overlap": candidate.lexical_overlap,
                "title_overlap": candidate.title_overlap,
                "strong_overlap": candidate.strong_overlap,
                "topic_overlap": candidate.topic_overlap,
                "exact_focus_hits": candidate.exact_focus_hits,
                "exact_strong_hits": candidate.exact_strong_hits,
                "domain_mismatch": candidate.domain_mismatch,
                "topic_mismatch": candidate.topic_mismatch,
            },
        }
        for candidate in candidates
    ]


def _build_candidate_clusters(
    buckets: list[list[EvidenceCandidate]],
    *,
    query_context: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = [
        candidate
        for candidate in _flatten_candidates(buckets)
        if _passes_relevance_gate(candidate, allow_weak=True) or candidate.coherence_score >= 0.42
    ]
    cluster_result = cluster_evidence(query_context, _candidate_cluster_inputs(candidates))
    return list(cluster_result.get("clusters") or [])


def _cluster_subject(cluster: dict[str, Any]) -> str:
    terms = [str(token).strip().replace("_", " ") for token in list(cluster.get("signature_terms") or []) if str(token).strip()]
    if terms:
        return ", ".join(terms[:3])
    dominant_topic = str(cluster.get("dominant_topic") or "").strip().replace("_", " ")
    if dominant_topic:
        return dominant_topic
    return str(cluster.get("cluster_id") or "").strip().replace("_", " ")


def _pick_primary_candidate(
    buckets: list[list[EvidenceCandidate]],
    *,
    selected_cluster_id: str | None = None,
    query_context: dict[str, Any] | None = None,
) -> tuple[EvidenceCandidate | None, bool]:
    qc = query_context or {}
    _query_has_signals = bool(
        (qc.get("tokens") or [])
        or (qc.get("strong_terms") or [])
        or (qc.get("topics") or [])
        or (qc.get("domains") or [])
    )
    scoped_buckets = (
        [
            [candidate for candidate in bucket if candidate.cluster_id == selected_cluster_id]
            for bucket in buckets
        ]
        if selected_cluster_id and _query_has_signals
        else buckets
    )
    for bucket in scoped_buckets[:-1]:
        concrete_rows = [item for item in bucket if item.concrete and _passes_relevance_gate(item)]
        if concrete_rows:
            return concrete_rows[0], False

    # When there are no query signals, the relevance gate is meaningless (no tokens to compare
    # against). Fall back to any concrete item ranked by score, trusting the retrieval similarity.
    if not _query_has_signals:
        for bucket in scoped_buckets[:-1]:
            concrete_rows = [item for item in bucket if item.concrete]
            if concrete_rows:
                return concrete_rows[0], False

    for bucket in scoped_buckets[:-1]:
        weak_rows = [item for item in bucket if _passes_relevance_gate(item, allow_weak=True)]
        if weak_rows:
            return weak_rows[0], True
    return None, True


def _diagnostic_step(candidate: EvidenceCandidate, *, lang: str) -> str:
    if lang == "fr":
        if candidate.evidence_type == "KB article":
            return f"Validez d'abord ce ticket par rapport a l'article {candidate.reference} avant d'appliquer son guidance."
        if candidate.evidence_type == "related problem":
            return f"Comparez cet incident avec le probleme {candidate.reference} pour verifier si la cause racine documentee correspond."
        if candidate.evidence_type == "comment":
            return f"Verifiez si le commentaire {candidate.reference} decrit bien le meme symptome avant de reutiliser le correctif."
        return f"Comparez ce ticket avec {candidate.reference} pour confirmer si la resolution documentee s'applique."

    if candidate.evidence_type == "KB article":
        return f"Validate this ticket against KB article {candidate.reference} before applying its guidance."
    if candidate.evidence_type == "related problem":
        return f"Compare this incident with problem {candidate.reference} to confirm whether the documented root cause matches."
    if candidate.evidence_type == "comment":
        return f"Confirm that comment {candidate.reference} describes the same symptom before reusing its fix."
    return f"Compare this ticket with {candidate.reference} to confirm whether the documented resolution applies."


def _supporting_evidence(
    primary: EvidenceCandidate,
    buckets: list[list[EvidenceCandidate]],
    *,
    selected_cluster_id: str | None = None,
) -> list[EvidenceCandidate]:
    support: list[EvidenceCandidate] = [primary]
    primary_basis = primary.action_text or primary.excerpt
    cluster_rows = [
        candidate
        for candidate in _flatten_candidates(buckets)
        if candidate.reference != primary.reference and (not selected_cluster_id or candidate.cluster_id == selected_cluster_id)
    ]
    cluster_rows.sort(
        key=lambda candidate: (
            1 if candidate.action_text and primary.action_text and _texts_agree(primary.action_text, candidate.action_text) else 0,
            candidate.coherence_score,
            candidate.strong_overlap,
            candidate.relevance,
        ),
        reverse=True,
    )
    for candidate in cluster_rows:
        if not _passes_relevance_gate(candidate, allow_weak=True):
            continue
        candidate_basis = candidate.action_text or candidate.excerpt
        if _texts_agree(primary_basis, candidate_basis) or candidate.coherence_score >= 0.58:
            support.append(candidate)
        if len(support) >= 3:
            break
    return support


def _recommendation_mode(primary: EvidenceCandidate, *, tentative: bool) -> str:
    return _MODE_BY_EVIDENCE.get(primary.evidence_type, "evidence_grounded")


def _action_agreement_count(primary: EvidenceCandidate, support: list[EvidenceCandidate]) -> int:
    primary_action = primary.action_text or ""
    if not primary_action:
        return 0
    agreed = 1
    for candidate in support[1:]:
        candidate_action = candidate.action_text or ""
        if candidate_action and _texts_agree(primary_action, candidate_action):
            agreed += 1
    return agreed


def _confidence_score(
    primary: EvidenceCandidate,
    *,
    support: list[EvidenceCandidate],
    tentative: bool,
    source_label: str,
    agreement_count: int,
) -> float:
    base = _EVIDENCE_BASE_WEIGHTS.get(primary.evidence_type, 0.55)
    semantic_bonus = max(
        0.0,
        min(ADVISOR_CONFIDENCE_WEIGHTS["semantic_bonus_cap"], primary.score * ADVISOR_CONFIDENCE_WEIGHTS["semantic_bonus_cap"]),
    )
    lexical_bonus = min(
        ADVISOR_CONFIDENCE_WEIGHTS["lexical_bonus_cap"],
        (primary.lexical_overlap * 0.06) + (primary.exact_focus_hits * 0.02) + (primary.strong_overlap * 0.04),
    )
    domain_bonus = (
        ADVISOR_CONFIDENCE_WEIGHTS["anchor_bonus"]
        if not primary.domain_mismatch and not primary.topic_mismatch and (
            primary.lexical_overlap >= 0.16 or primary.exact_focus_hits >= 2 or primary.exact_strong_hits >= 2
        )
        else 0.0
    )
    action_basis = primary.action_text or primary.excerpt
    action_bonus = min(ADVISOR_CONFIDENCE_WEIGHTS["action_bonus_cap"], _actionability_score(action_basis) * ADVISOR_CONFIDENCE_WEIGHTS["action_bonus_cap"])
    support_bonus = min(
        ADVISOR_CONFIDENCE_WEIGHTS["support_bonus_cap"],
        max(0, len(support) - 1) * ADVISOR_CONFIDENCE_WEIGHTS["support_bonus_step"],
    )
    agreement_bonus = ADVISOR_CONFIDENCE_WEIGHTS["agreement_bonus"] if agreement_count >= 2 else 0.0
    source_bonus = _SOURCE_LABEL_BONUS.get(source_label, 0.0)
    tentative_penalty = ADVISOR_CONFIDENCE_WEIGHTS["tentative_penalty"] if tentative else 0.0
    mismatch_penalty = ADVISOR_CONFIDENCE_WEIGHTS["domain_mismatch_penalty"] if primary.domain_mismatch else 0.0
    topic_mismatch_penalty = ADVISOR_CONFIDENCE_WEIGHTS["topic_mismatch_penalty"] if primary.topic_mismatch else 0.0
    weak_lexical_penalty = (
        ADVISOR_CONFIDENCE_WEIGHTS["weak_lexical_penalty"]
        if primary.lexical_overlap < 0.08 and primary.exact_focus_hits == 0 and primary.exact_strong_hits == 0
        else (
            ADVISOR_CONFIDENCE_WEIGHTS["medium_lexical_penalty"]
            if primary.lexical_overlap < 0.18 and primary.exact_focus_hits < 2 and primary.exact_strong_hits < 2
            else 0.0
        )
    )
    confidence = (
        base
        + semantic_bonus
        + lexical_bonus
        + domain_bonus
        + action_bonus
        + support_bonus
        + agreement_bonus
        + source_bonus
        - tentative_penalty
        - weak_lexical_penalty
        - mismatch_penalty
        - topic_mismatch_penalty
    )
    return round(max(0.0, min(1.0, confidence)), 4)


def _subject_terms(query_context: dict[str, Any], *, limit: int = 4) -> list[str]:
    terms = [_display_term(token) for token in _ordered_query_terms(query_context)]
    return [term for term in terms if term][:limit]


def _query_context_domains(query_context: dict[str, Any]) -> set[str]:
    domains = {
        str(domain or "").strip().lower()
        for domain in list(query_context.get("domains") or [])
        if str(domain or "").strip()
    }
    category = str((query_context.get("metadata") or {}).get("category") or "").strip().lower()
    if category:
        domains.add(category)
    return {domain for domain in domains if domain in _CATEGORY_HINTS}


def _source_signal_tokens(query_context: dict[str, Any], source: str) -> set[str]:
    return {
        str(token or "").strip().lower()
        for token in list(query_context.get(source) or [])
        if str(token or "").strip()
    }


def _topic_signal_profile(
    query_context: dict[str, Any],
    *,
    topic: str,
    cluster_id: str | None = None,
    evidence_topics: list[str] | None = None,
) -> dict[str, Any]:
    hints = set(_TOPIC_HINTS.get(topic) or [])
    unique_hints = set(_UNIQUE_TOPIC_HINTS.get(topic) or [])
    all_tokens = set(_ordered_query_terms(query_context))
    explicit_hits: set[str] = set()
    supporting_hits: set[str] = set()
    weak_hits: set[str] = set()
    score = 0.0

    for source, weight in _QUERY_TOPIC_SOURCE_WEIGHTS.items():
        source_tokens = _source_signal_tokens(query_context, source)
        unique_hits = source_tokens.intersection(unique_hints)
        strong_hits = source_tokens.intersection(hints.difference(_WEAK_FAMILY_TOKENS).difference(unique_hints))
        weak_source_hits = source_tokens.intersection(hints.intersection(_WEAK_FAMILY_TOKENS))
        explicit_hits.update(unique_hits)
        supporting_hits.update(strong_hits)
        weak_hits.update(weak_source_hits)
        score += len(unique_hits) * weight
        score += len(strong_hits) * (weight * 0.55)
        score += len(weak_source_hits) * 0.08

    query_topics = {
        str(candidate or "").strip().lower()
        for candidate in list(query_context.get("topics") or [])
        if str(candidate or "").strip()
    }
    if topic in query_topics:
        score += 0.35

    query_domains = _query_context_domains(query_context)
    domain_hits = query_domains.intersection(_TOPIC_DOMAIN_EXPECTATIONS.get(topic, frozenset()))
    if domain_hits:
        score += 0.9 + (0.2 * max(0, len(domain_hits) - 1))

    operation_hits = all_tokens.intersection(_OPERATION_SIGNAL_HINTS).intersection(hints)
    context_hits = all_tokens.intersection(_CONTEXT_SIGNAL_HINTS)
    object_hits = all_tokens.intersection(_AFFECTED_OBJECT_HINTS).intersection(hints)
    if operation_hits and (explicit_hits or supporting_hits):
        score += 0.85
    if context_hits and (explicit_hits or supporting_hits or operation_hits):
        score += 0.35
    if object_hits and (explicit_hits or supporting_hits):
        score += 0.45

    if cluster_id == topic and (explicit_hits or supporting_hits or domain_hits):
        score += 0.7
    if topic in set(evidence_topics or []) and (explicit_hits or supporting_hits):
        score += 0.3

    auth_anchor_hits: set[str] = set()
    if topic == "auth_path":
        auth_anchor_hits = all_tokens.intersection(_AUTH_PATH_REQUIRED_ANCHORS)
        if auth_anchor_hits:
            score += 0.8 * len(auth_anchor_hits)
        else:
            score = min(score, _FAMILY_SELECTION_THRESHOLDS["medium_score"] - 0.1)

    structured_signal_count = len(explicit_hits) + len(supporting_hits)
    if domain_hits:
        structured_signal_count += 1
    if operation_hits:
        structured_signal_count += 1
    if object_hits:
        structured_signal_count += 1
    if context_hits and (explicit_hits or supporting_hits or operation_hits):
        structured_signal_count += 1

    weak_keyword_only = not explicit_hits and not supporting_hits and bool(weak_hits)
    accepted = (
        not weak_keyword_only
        and score >= _FAMILY_SELECTION_THRESHOLDS["score_min"]
        and (
            bool(explicit_hits)
            or structured_signal_count >= _FAMILY_SELECTION_THRESHOLDS["structured_min"]
            or (cluster_id == topic and structured_signal_count >= 1)
        )
    )
    if topic == "auth_path" and not auth_anchor_hits and not explicit_hits:
        accepted = False

    return {
        "topic": topic,
        "score": round(score, 4),
        "explicit_hits": sorted(explicit_hits),
        "supporting_hits": sorted(supporting_hits),
        "weak_hits": sorted(weak_hits),
        "domain_hits": sorted(domain_hits),
        "operation_hits": sorted(operation_hits),
        "context_hits": sorted(context_hits),
        "object_hits": sorted(object_hits),
        "auth_anchor_hits": sorted(auth_anchor_hits),
        "structured_signal_count": structured_signal_count,
        "weak_keyword_only": weak_keyword_only,
        "accepted": accepted,
    }


def _resolve_query_signal_family(
    query_context: dict[str, Any],
    *,
    cluster_id: str | None = None,
    evidence_topics: list[str] | None = None,
) -> dict[str, Any]:
    profiles = [
        _topic_signal_profile(
            query_context,
            topic=topic,
            cluster_id=cluster_id,
            evidence_topics=evidence_topics,
        )
        for topic in _TOPIC_HINTS
    ]
    ranked = sorted(profiles, key=lambda profile: (-float(profile["score"]), profile["topic"]))
    best = ranked[0] if ranked else None
    if best is None or not best["accepted"]:
        return {
            "selected_family": None,
            "confidence": "low",
            "basis": "weak_keywords",
            "score": 0.0,
            "margin": 0.0,
            "profile": best or {},
            "profiles": ranked,
        }

    next_score = max(float(profile["score"]) for profile in ranked[1:] if profile["accepted"]) if any(profile["accepted"] for profile in ranked[1:]) else 0.0
    margin = round(float(best["score"]) - next_score, 4)
    explicit_hit_count = len(list(best["explicit_hits"]))
    structured_signal_count = int(best["structured_signal_count"])

    if explicit_hit_count >= 1:
        basis = "explicit_signals"
    elif structured_signal_count >= _FAMILY_SELECTION_THRESHOLDS["structured_min"]:
        basis = "structured_signals"
    else:
        basis = "weak_keywords"

    confidence = "low"
    if basis != "weak_keywords":
        if explicit_hit_count >= _FAMILY_SELECTION_THRESHOLDS["high_explicit_hits"] or (
            float(best["score"]) >= _FAMILY_SELECTION_THRESHOLDS["high_score"]
            and margin >= _FAMILY_SELECTION_THRESHOLDS["margin_min"]
        ):
            confidence = "high"
        elif float(best["score"]) >= _FAMILY_SELECTION_THRESHOLDS["medium_score"] and (
            margin >= _FAMILY_SELECTION_THRESHOLDS["margin_min"]
            or explicit_hit_count >= 1
            or structured_signal_count > _FAMILY_SELECTION_THRESHOLDS["structured_min"]
        ):
            confidence = "medium"

    if best["topic"] == "auth_path" and not list(best["auth_anchor_hits"]) and confidence != "high":
        confidence = "low"
    if float(best["score"]) < _FAMILY_SELECTION_THRESHOLDS["broad_family_score"] and best["topic"] == "auth_path" and explicit_hit_count < 1:
        confidence = "low"

    selected_family = str(best["topic"]) if confidence in {"medium", "high"} else None
    return {
        "selected_family": selected_family,
        "confidence": confidence,
        "basis": basis,
        "score": round(float(best["score"]), 4),
        "margin": margin,
        "profile": best,
        "profiles": ranked,
    }


def _cluster_family_supported(
    query_context: dict[str, Any],
    *,
    primary: EvidenceCandidate,
    support: list[EvidenceCandidate],
) -> bool:
    if primary.cluster_id not in _TOPIC_HINTS or primary.topic_mismatch or primary.domain_mismatch:
        return False
    if (
        primary.exact_focus_hits >= 1
        or primary.exact_strong_hits >= 1
        or primary.strong_overlap >= ADVISOR_CAUSE_CONFIRMATION["supported_excerpt_overlap"]
        or primary.relevance >= ADVISOR_CAUSE_CONFIRMATION["supported_excerpt_relevance"]
        or primary.context_score >= ADVISOR_CAUSE_CONFIRMATION["supported_excerpt_context_strong"]
    ):
        return True
    query_tokens = set(_ordered_query_terms(query_context))
    if query_tokens.intersection(set(_UNIQUE_TOPIC_HINTS.get(primary.cluster_id) or [])):
        return True
    return any(
        candidate.reference != primary.reference
        and candidate.cluster_id == primary.cluster_id
        and not candidate.topic_mismatch
        and not candidate.domain_mismatch
        and candidate.coherence_score >= ADVISOR_CAUSE_CONFIRMATION["candidate_gate_coherence"]
        for candidate in support[1:]
    )


def _preferred_query_topic(query_context: dict[str, Any]) -> str | None:
    resolution = _resolve_query_signal_family(query_context)
    selected_family = str(resolution.get("selected_family") or "").strip().lower()
    return selected_family if selected_family in _TOPIC_HINTS else None


def _preferred_signal_topic(signals: dict[str, Any]) -> str | None:
    dominant_topic = str(signals.get("dominant_topic_overlap") or signals.get("dominant_topic") or "").strip().lower()
    if dominant_topic in _TOPIC_HINTS:
        return dominant_topic
    return None


def _has_specific_guidance_context(query_context: dict[str, Any]) -> bool:
    resolution = _resolve_query_signal_family(query_context)
    if str(resolution.get("confidence") or "").strip().lower() in {"medium", "high"}:
        return True
    strong_terms = [str(term).strip().lower() for term in list(query_context.get("strong_terms") or []) if str(term).strip()]
    salient_terms = [term for term in strong_terms if term not in _LOW_SIGNAL_TOKENS and term not in _WEAK_FAMILY_TOKENS]
    return len(salient_terms) >= 3


def _safe_diagnostic_action(query_context: dict[str, Any], *, lang: str) -> str | None:
    resolution = _resolve_query_signal_family(query_context)
    if str(resolution.get("confidence") or "").strip().lower() not in {"medium", "high"}:
        return None
    preferred_topic = str(resolution.get("selected_family") or "").strip().lower()
    if preferred_topic not in _TOPIC_HINTS:
        return None
    return topic_safe_diagnostic_action(preferred_topic, lang=lang)


def _tentative_diagnostic_next_step(
    query_context: dict[str, Any],
    *,
    candidate_action: str | None,
    candidate_reference: str | None,
    lang: str,
) -> str | None:
    safe_action = _safe_diagnostic_action(query_context, lang=lang)
    if safe_action:
        return safe_action

    action_text = _action_step_text(candidate_action or "")
    if not action_text:
        return None

    reference = _normalize_text(candidate_reference or "")
    subject = _subject_label(query_context) or (
        "the affected path" if lang == "en" else "le perimetre affecte"
    )
    if reference:
        return (
            f"Validate on one affected case that the current symptoms still match {reference} before applying '{_truncate(action_text, limit=88)}' more broadly."
            if lang == "en"
            else f"Validez d'abord sur un cas affecte que les symptomes actuels correspondent encore a {reference} avant d'appliquer '{_truncate(action_text, limit=88)}' plus largement."
        )
    return (
        f"Check one representative affected {subject} path and capture the current failure signal before applying '{_truncate(action_text, limit=88)}' more broadly."
        if lang == "en"
        else f"Controlez un cas representatif sur {subject} et capturez le signal d'echec actuel avant d'appliquer '{_truncate(action_text, limit=88)}' plus largement."
    )


def _build_response_text(
    *,
    recommended_action: str | None,
    reasoning: str,
    confidence: float,
    evidence_sources: list[dict[str, str | None]],
    lang: str,
    display_mode: str,
) -> str:
    if display_mode == _NO_STRONG_MATCH_DISPLAY:
        action_text = recommended_action or (
            "Aucune solution forte disponible pour l'instant."
            if lang == "fr"
            else "No strong evidence-backed solution available yet."
        )
        if lang == "fr":
            return (
                f"Action recommandee:\n{action_text}\n\n"
                f"Justification:\n{reasoning}\n\nConfiance:\n{round(confidence * 100)}%\n\nSources:\n"
            ).strip()
        return (
            f"Recommended action:\n{action_text}\n\n"
            f"Reasoning:\n{reasoning}\n\nConfidence:\n{round(confidence * 100)}%\n\nEvidence sources:\n"
        ).strip()

    evidence_lines = [
        f"- {row['evidence_type']}: {row['reference']} - {row['excerpt']}"
        for row in evidence_sources
        if row.get("reference")
    ]
    label = "Action recommandee" if lang == "fr" else "Recommended action"
    reason_label = "Justification" if lang == "fr" else "Reasoning"
    source_label = "Sources" if lang == "fr" else "Evidence sources"
    confidence_label = "Confiance" if lang == "fr" else "Confidence"
    return (
        f"{label}:\n{recommended_action or ''}\n\n"
        f"{reason_label}:\n{reasoning}\n\n"
        f"{confidence_label}:\n{round(confidence * 100)}%\n\n"
        f"{source_label}:\n" + "\n".join(evidence_lines)
    ).strip()


def _conflict_next_checks(query_context: dict[str, Any], conflicting_clusters: list[dict[str, Any]], *, lang: str) -> list[str]:
    checks: list[str] = []
    cluster_subjects = [_cluster_subject(cluster) for cluster in conflicting_clusters[:2] if _cluster_subject(cluster)]
    if len(cluster_subjects) >= 2:
        checks.append(
            (
                f"Confirmez d'abord si l'incident courant releve de {cluster_subjects[0]} ou de {cluster_subjects[1]} avant de reutiliser un correctif historique."
                if lang == "fr"
                else f"Confirm whether the current incident belongs to {cluster_subjects[0]} or {cluster_subjects[1]} before reusing a historical fix."
            )
        )
    checks.append(_validation_step(query_context, lang=lang))
    checks.append(
        (
            "Capturez un extrait de journal, une erreur ou un objet en echec qui identifie clairement le composant en cause."
            if lang == "fr"
            else "Capture one current log, error, or failing object that clearly identifies the affected component."
        )
    )
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in checks:
        normalized = _normalize_text(raw)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
        if len(deduped) >= 3:
            break
    return deduped


def _insufficient_evidence_payload(
    retrieval: dict[str, Any],
    *,
    query_context: dict[str, Any],
    lang: str,
    reasoning: str,
    conflicting_clusters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    confidence = ADVISOR_FALLBACK_CONFIDENCE["insufficient_evidence"]
    conflict_lines: list[str] = []
    cluster_subjects = [_cluster_subject(cluster) for cluster in list(conflicting_clusters or [])[:2] if _cluster_subject(cluster)]
    if cluster_subjects:
        if lang == "fr":
            conflict_lines.append(f"Signaux concurrents detectes: {' ; '.join(cluster_subjects)}.")
        else:
            conflict_lines.append(f"Conflicting evidence clusters detected: {'; '.join(cluster_subjects)}.")
    conflict_lines.append(
        (
            "Aucune famille d'incident unique ne dispose d'un support suffisamment net pour recommander un correctif."
            if lang == "fr"
            else "No single incident family has enough support to recommend one fix safely."
        )
    )
    next_checks = _conflict_next_checks(query_context, list(conflicting_clusters or []), lang=lang)
    response_text = _build_response_text(
        recommended_action=None,
        reasoning=reasoning,
        confidence=confidence,
        evidence_sources=[],
        lang=lang,
        display_mode=_NO_STRONG_MATCH_DISPLAY,
    )
    return {
        "recommended_action": None,
        "reasoning": reasoning,
        "probable_root_cause": None,
        "root_cause": None,
        "supporting_context": None,
        "why_this_matches": [],
        "evidence_sources": [],
        "tentative": False,
        "confidence": confidence,
        "confidence_band": _confidence_band(confidence),
        "confidence_label": classify_confidence(confidence),
        "source_label": str(retrieval.get("source") or "fallback_rules"),
        "recommendation_mode": "insufficient_evidence",
        "mode": _NO_STRONG_MATCH_DISPLAY,
        "display_mode": _NO_STRONG_MATCH_DISPLAY,
        "match_summary": None,
        "next_best_actions": next_checks,
        "incident_cluster": None,
        "impact_summary": _impact_summary(query_context, lang=lang, cluster=None),
        "filtered_weak_match": False,
        "action_relevance_score": 0.0,
        "validation_steps": next_checks[:2],
        "fallback_action": None,
        "missing_information": conflict_lines[:3],
        "response_text": response_text,
    }


def _fallback_diagnostic_payload(
    retrieval: dict[str, Any],
    *,
    query_context: dict[str, Any],
    lang: str,
    reasoning: str,
    filtered_weak_match: bool,
    action_relevance_score: float,
    probable_root_cause: str | None = None,
    supporting_context: str | None = None,
    why_this_matches: list[str] | None = None,
    match_summary: str | None = None,
    incident_cluster: dict[str, Any] | None = None,
    impact_summary: str | None = None,
    evidence_sources: list[dict[str, str | None]] | None = None,
    action_steps: list[GroundedActionStep] | None = None,
) -> dict[str, Any] | None:
    grounded_steps = list(action_steps or [])
    grounded_primary_action = grounded_steps[0].text if grounded_steps else None
    grounded_reference = grounded_steps[0].evidence[0] if grounded_steps and grounded_steps[0].evidence else None
    recommended_action = _tentative_diagnostic_next_step(
        query_context,
        candidate_action=grounded_primary_action,
        candidate_reference=grounded_reference,
        lang=lang,
    ) or _safe_diagnostic_action(query_context, lang=lang)
    if not recommended_action:
        return _no_strong_match_payload(
            retrieval,
            query_context=query_context,
            lang=lang,
            reasoning=reasoning,
            filtered_weak_match=filtered_weak_match,
            action_relevance_score=action_relevance_score,
        )

    confidence = (
        ADVISOR_FALLBACK_CONFIDENCE["weak_match_filtered"]
        if filtered_weak_match
        else ADVISOR_FALLBACK_CONFIDENCE["fallback_diagnostic"]
    )
    next_best_actions: list[str] = []
    if grounded_primary_action:
        normalized_primary = _action_step_text(grounded_primary_action)
        if normalized_primary and normalized_primary.casefold() != recommended_action.casefold():
            next_best_actions.append(normalized_primary)
    if grounded_steps:
        next_best_actions.extend(step.text for step in grounded_steps[1:])
    else:
        next_best_actions.extend(
            _next_best_actions(
                recommended_action=recommended_action,
                probable_root_cause=probable_root_cause,
                tentative=True,
                query_context=query_context,
                support=[],
                lang=lang,
            )
        )
    deduped_next_actions: list[str] = []
    seen_next: set[str] = set()
    for item in next_best_actions:
        normalized_item = _normalize_text(item)
        key = normalized_item.casefold()
        if not normalized_item or key in seen_next or key == recommended_action.casefold():
            continue
        seen_next.add(key)
        deduped_next_actions.append(normalized_item)
        if len(deduped_next_actions) >= 4:
            break
    normalized_evidence = evidence_sources or []
    display_mode = _TENTATIVE_DIAGNOSTIC_DISPLAY
    validation_steps = build_validation_steps(
        query_context,
        recommended_action=recommended_action,
        supporting_context=supporting_context,
        lang=lang,
    )
    fallback_action = build_fallback_action(
        query_context,
        probable_root_cause=probable_root_cause,
        supporting_context=supporting_context,
        lang=lang,
    )
    fallback_terms = _match_terms(query_context, recommended_action)
    fallback_match_summary = (
        f"Correspondance sur {', '.join(fallback_terms)}."
        if lang == "fr" and fallback_terms
        else (f"Matched on {', '.join(fallback_terms)}." if fallback_terms else None)
    )
    return {
        "recommended_action": recommended_action,
        "reasoning": reasoning,
        "probable_root_cause": probable_root_cause,
        "root_cause": None,
        "supporting_context": supporting_context,
        "why_this_matches": list(why_this_matches or []),
        "evidence_sources": normalized_evidence[:2],
        "tentative": True,
        "confidence": confidence,
        "confidence_band": _confidence_band(confidence),
        "confidence_label": classify_confidence(confidence),
        "source_label": str(retrieval.get("source") or "fallback_rules"),
        "recommendation_mode": "fallback_diagnostic",
        "mode": display_mode,
        "match_summary": match_summary or fallback_match_summary,
        "next_best_actions": deduped_next_actions,
        "incident_cluster": incident_cluster,
        "impact_summary": impact_summary,
        "filtered_weak_match": filtered_weak_match,
        "action_relevance_score": round(max(0.0, min(1.0, action_relevance_score)), 4),
        "validation_steps": validation_steps,
        "workflow_steps": [step.text for step in grounded_steps] if grounded_steps else [recommended_action],
        "fallback_action": fallback_action,
        "display_mode": display_mode,
        "action_steps": _serialize_action_steps(grounded_steps),
        "response_text": _build_response_text(
            recommended_action=recommended_action,
            reasoning=reasoning,
            confidence=confidence,
            evidence_sources=normalized_evidence[:2],
            lang=lang,
            display_mode=display_mode,
        ),
    }


def _no_strong_match_payload(
    retrieval: dict[str, Any],
    *,
    query_context: dict[str, Any],
    lang: str,
    reasoning: str | None = None,
    filtered_weak_match: bool = False,
    action_relevance_score: float = 0.0,
    _skip_llm: bool = False,
) -> dict[str, Any] | None:
    subject = ", ".join(_subject_terms(query_context))
    if not reasoning:
        if lang == "fr":
            reasoning = "Aucune evidence historisee n'a passe les garde-fous de pertinence; aucune solution fiable n'est affichee."
        else:
            reasoning = "No retrieved evidence passed the relevance guardrails, so no evidence-backed solution is shown."
    if lang == "fr" and subject:
        reasoning = f"{reasoning} Sujet detecte: {subject}."
    elif lang == "en" and subject:
        reasoning = f"{reasoning} Detected scope: {subject}."
    confidence = ADVISOR_FALLBACK_CONFIDENCE["cause_insufficient"]
    fallback_action = build_fallback_action(
        query_context,
        probable_root_cause=None,
        supporting_context=None,
        lang=lang,
    )

    # When not called as an internal base (e.g. from _low_trust_incident_fallback_payload),
    # always ask the LLM for a best-effort recommendation so the user never sees a blank card.
    llm_action_pkg = None
    if not _skip_llm:
        try:
            llm_action_pkg = generate_low_trust_incident_actions(
                ticket_title=str(query_context.get("title") or ""),
                ticket_description=str(query_context.get("description") or ""),
                ticket_category=str((query_context.get("metadata") or {}).get("category") or ""),
                ticket_priority=str((query_context.get("metadata") or {}).get("priority") or ""),
                attempted_steps=list((query_context.get("metadata") or {}).get("attempted_steps") or []),
                concurrent_families=[],
                deterministic_fallback=str(fallback_action or "") or None,
                language=lang,
            )
        except Exception:
            llm_action_pkg = None

    if llm_action_pkg is not None:
        display_mode = _DISPLAY_MODE_LLM_GENERAL
        recommended_action = llm_action_pkg.recommended_action
        next_best_actions = list(llm_action_pkg.next_best_actions)
        validation_steps = list(llm_action_pkg.validation_steps)
        ai_only_warning = True
        reasoning_note = str(llm_action_pkg.reasoning_note or "").strip()
        if reasoning_note:
            reasoning = reasoning_note
    else:
        display_mode = _NO_STRONG_MATCH_DISPLAY
        recommended_action = fallback_action
        next_best_actions = []
        validation_steps = (
            build_validation_steps(
                query_context,
                recommended_action=recommended_action,
                supporting_context=None,
                lang=lang,
            )
            if recommended_action
            else []
        )
        ai_only_warning = False

    return {
        "recommended_action": recommended_action,
        "reasoning": reasoning,
        "probable_root_cause": None,
        "root_cause": None,
        "supporting_context": None,
        "why_this_matches": [],
        "evidence_sources": [],
        "tentative": False,
        "confidence": confidence,
        "confidence_band": _confidence_band(confidence),
        "confidence_label": classify_confidence(confidence),
        "source_label": str(retrieval.get("source") or "fallback_rules"),
        "recommendation_mode": "fallback_diagnostic",
        "mode": display_mode,
        "match_summary": (
            f"Correspondance sur {subject}."
            if lang == "fr" and subject
            else (f"Matched on {subject}." if subject else None)
        ),
        "next_best_actions": next_best_actions,
        "incident_cluster": None,
        "impact_summary": _impact_summary(query_context, lang=lang, cluster=None),
        "filtered_weak_match": filtered_weak_match,
        "action_relevance_score": round(max(0.0, min(1.0, action_relevance_score)), 4),
        "validation_steps": validation_steps,
        "fallback_action": fallback_action,
        "display_mode": display_mode,
        "ai_only_warning": ai_only_warning,
        "response_text": _build_response_text(
            recommended_action=recommended_action,
            reasoning=reasoning,
            confidence=confidence,
            evidence_sources=[],
            lang=lang,
            display_mode=display_mode,
        ),
    }


def _low_trust_incident_fallback_payload(
    retrieval: dict[str, Any],
    *,
    query_context: dict[str, Any],
    lang: str,
    reasoning: str | None = None,
    filtered_weak_match: bool = False,
    action_relevance_score: float = 0.0,
    next_best_actions: list[str] | None = None,
    validation_steps: list[str] | None = None,
    missing_information: list[str] | None = None,
    concurrent_families: list[str] | None = None,
) -> dict[str, Any]:
    payload = _no_strong_match_payload(
        retrieval,
        query_context=query_context,
        lang=lang,
        reasoning=reasoning,
        filtered_weak_match=filtered_weak_match,
        action_relevance_score=action_relevance_score,
        _skip_llm=True,
    )
    if next_best_actions is not None:
        payload["next_best_actions"] = [
            _normalize_text(item)
            for item in list(next_best_actions)
            if _normalize_text(item)
        ][:4]
    if validation_steps is not None:
        payload["validation_steps"] = [
            _normalize_text(item)
            for item in list(validation_steps)
            if _normalize_text(item)
        ][:3]
    if missing_information is not None:
        payload["missing_information"] = [
            _normalize_text(item)
            for item in list(missing_information)
            if _normalize_text(item)
        ][:3]

    attempted_steps = list((query_context.get("metadata") or {}).get("attempted_steps") or [])
    families = list(concurrent_families or [])
    low_trust_action_package = generate_low_trust_incident_actions(
        ticket_title=str(query_context.get("title") or ""),
        ticket_description=str(query_context.get("description") or ""),
        ticket_category=str((query_context.get("metadata") or {}).get("category") or ""),
        ticket_priority=str((query_context.get("metadata") or {}).get("priority") or ""),
        attempted_steps=attempted_steps,
        concurrent_families=families,
        deterministic_fallback=str(payload.get("fallback_action") or "") or None,
        language=lang,
    )
    _has_specific_signals = bool(
        (query_context.get("strong_terms") or [])
        and (
            (query_context.get("topics") or [])
            or (query_context.get("domains") or [])
        )
    )
    llm_advisory = (
        build_llm_general_advisory(
            ticket_title=str(query_context.get("title") or ""),
            ticket_description=str(query_context.get("description") or ""),
            ticket_category=str((query_context.get("metadata") or {}).get("category") or ""),
            ticket_priority=str((query_context.get("metadata") or {}).get("priority") or ""),
            attempted_steps=attempted_steps,
            concurrent_families=families,
            language=lang,
        )
        if not _has_specific_signals
        else None
    )
    payload["base_recommended_action"] = payload.get("fallback_action")
    payload["base_next_best_actions"] = list(payload.get("next_best_actions") or [])
    payload["base_validation_steps"] = list(payload.get("validation_steps") or [])
    payload["action_refinement_source"] = "none"
    payload["ai_only_warning"] = True
    if low_trust_action_package is not None:
        payload["display_mode"] = _DISPLAY_MODE_LLM_GENERAL
        payload["mode"] = _DISPLAY_MODE_LLM_GENERAL
        payload["recommendation_mode"] = "llm_assisted"
        payload["knowledge_source"] = "llm_general_knowledge"
        payload["recommended_action"] = low_trust_action_package.recommended_action
        payload["next_best_actions"] = list(low_trust_action_package.next_best_actions)
        payload["validation_steps"] = list(low_trust_action_package.validation_steps)
        payload["action_refinement_source"] = "llm_general_knowledge"
        reasoning_note = str(low_trust_action_package.reasoning_note or "").strip()
        if reasoning_note:
            payload["reasoning"] = reasoning_note
        payload["response_text"] = _build_response_text(
            recommended_action=payload.get("recommended_action"),
            reasoning=str(payload.get("reasoning") or ""),
            confidence=float(payload.get("confidence") or _LLM_ADVISORY_CONFIDENCE),
            evidence_sources=[],
            lang=lang,
            display_mode=_DISPLAY_MODE_LLM_GENERAL,
        )
    if llm_advisory is not None:
        payload["knowledge_source"] = llm_advisory.knowledge_source
        payload["llm_general_advisory"] = {
            "probable_causes": llm_advisory.probable_causes,
            "suggested_checks": llm_advisory.suggested_checks,
            "escalation_hint": llm_advisory.escalation_hint,
            "knowledge_source": llm_advisory.knowledge_source,
            "confidence": llm_advisory.confidence,
            "language": llm_advisory.language,
        }
    return payload


def build_resolution_advice(retrieval: dict[str, Any], *, lang: str = "en") -> dict[str, Any] | None:
    query_context = _query_context(retrieval)
    buckets = _build_buckets(retrieval, query_context=query_context)
    candidate_clusters = _build_candidate_clusters(buckets, query_context=query_context)
    selected_cluster = select_primary_cluster(candidate_clusters)
    selected_cluster_id = str((selected_cluster or {}).get("cluster_id") or "").strip().lower() or None
    cluster_conflict = evidence_conflict_detected(selected_cluster, candidate_clusters)
    retrieval["evidence_clusters"] = {
        "selected_cluster_id": selected_cluster_id,
        "excluded_cluster_count": max(0, len(candidate_clusters) - (1 if selected_cluster_id else 0)),
        "coherence_score": round(float((selected_cluster or {}).get("score") or 0.0), 4),
        "evidence_conflict_flag": cluster_conflict,
        "clusters": [
            {
                "cluster_id": str(cluster.get("cluster_id") or ""),
                "score": round(float(cluster.get("score") or 0.0), 4),
                "support_count": int(cluster.get("support_count") or 0),
                "candidate_count": int(cluster.get("candidate_count") or 0),
                "dominant_topic": cluster.get("dominant_topic"),
                "signature_terms": list(cluster.get("signature_terms") or []),
                "references": list(cluster.get("references") or [])[:3],
            }
            for cluster in candidate_clusters[:4]
        ],
    }
    if cluster_conflict:
        reasoning = (
            "L'evidence recuperee se repartit entre plusieurs familles d'incident; aucun chemin de resolution unique ne peut etre recommande en securite."
            if lang == "fr"
            else "Evidence is split across different incident families, so no single remediation path can be recommended safely."
        )
        return _insufficient_evidence_payload(
            retrieval,
            query_context=query_context,
            lang=lang,
            reasoning=reasoning,
            conflicting_clusters=candidate_clusters,
        )
    if len(candidate_clusters) >= 2 and selected_cluster is None:
        reasoning = (
            "Aucune famille d'incident n'apporte un support assez coherent pour recommander un correctif."
            if lang == "fr"
            else "No incident family provides enough coherent support to recommend a fix."
        )
        return _insufficient_evidence_payload(
            retrieval,
            query_context=query_context,
            lang=lang,
            reasoning=reasoning,
            conflicting_clusters=candidate_clusters,
        )

    _query_has_signals = bool(
        (query_context.get("tokens") or [])
        or (query_context.get("strong_terms") or [])
        or (query_context.get("topics") or [])
        or (query_context.get("domains") or [])
    )
    low_signal_query = not any(query_context.get(key) for key in ("strong_terms", "topics", "domains"))
    preferred_query_topic = _preferred_query_topic(query_context)
    query_category = str((query_context.get("metadata") or {}).get("category") or "").strip().lower()
    aligned_raw_evidence_present = any(
        not bool(row.get("domain_mismatch")) and not bool(row.get("topic_mismatch"))
        for row in [
            *list(retrieval.get("similar_tickets") or []),
            *list(retrieval.get("kb_articles") or []),
            *list(retrieval.get("solution_recommendations") or []),
        ]
    )

    # Compute incident_cluster early so it can be included in no-primary early returns.
    incident_cluster = _incident_cluster(retrieval, query_context, lang=lang, selected_cluster_id=selected_cluster_id)
    impact_summary = _impact_summary(query_context, lang=lang, cluster=incident_cluster)

    # Extract probable_root_cause from related problems for early-return paths.
    _early_probable_root_cause: str | None = None
    for _prob_row in list(retrieval.get("related_problems") or []):
        _rc = str(_prob_row.get("root_cause") or "").strip()
        if _rc:
            _early_probable_root_cause = _rc
            break

    primary, tentative = _pick_primary_candidate(
        buckets,
        selected_cluster_id=selected_cluster_id,
        query_context=query_context,
    )
    if primary is None:
        if any(
            not bool(row.get("domain_mismatch")) and not bool(row.get("topic_mismatch"))
            for row in list(retrieval.get("related_problems") or [])
        ) and _has_specific_guidance_context(query_context):
            reasoning = (
                "Problem evidence suggests a likely incident family, so a cautious ticket-specific diagnostic is returned."
                if lang == "en"
                else "La preuve issue des problemes suggere une famille d'incident probable, donc un diagnostic prudent et specifique au ticket est renvoye."
            )
            return _fallback_diagnostic_payload(
                retrieval,
                query_context=query_context,
                lang=lang,
                reasoning=reasoning,
                filtered_weak_match=False,
                action_relevance_score=0.0,
                probable_root_cause=_early_probable_root_cause,
                incident_cluster=incident_cluster,
                impact_summary=impact_summary,
            )
        if aligned_raw_evidence_present and _has_specific_guidance_context(query_context) and not low_signal_query:
            reasoning = (
                "The historical evidence is too generic to reuse directly, so a safe ticket-specific diagnostic is returned."
                if lang == "en"
                else "Les preuves historiques restent trop generiques pour etre reutilisees directement, donc un diagnostic prudent et specifique au ticket est renvoye."
            )
            return _fallback_diagnostic_payload(
                retrieval,
                query_context=query_context,
                lang=lang,
                reasoning=reasoning,
                filtered_weak_match=False,
                action_relevance_score=0.0,
                probable_root_cause=_early_probable_root_cause,
                incident_cluster=incident_cluster,
                impact_summary=impact_summary,
            )
        if (
            not aligned_raw_evidence_present
            and (
                preferred_query_topic in {"network_access", "auth_path", "database_data", "mail_transport"}
                or query_category in {"network", "security", "email"}
            )
            and _has_specific_guidance_context(query_context)
        ):
            reasoning = (
                "No aligned historical fix was found, so only low-trust general diagnostic guidance is available."
                if lang == "en"
                else "Aucun correctif historique aligne n'a ete trouve, donc seule une guidance diagnostique generale a faible confiance est disponible."
            )
            return _low_trust_incident_fallback_payload(
                retrieval,
                query_context=query_context,
                lang=lang,
                reasoning=reasoning,
                concurrent_families=_extract_concurrent_families(candidate_clusters),
            )
        if low_signal_query:
            return _insufficient_evidence_payload(
                retrieval,
                query_context=query_context,
                lang=lang,
                reasoning=(
                    "The retrieved signals stay too generic to recommend a safe next step."
                    if lang == "en"
                    else "Les signaux recuperes restent trop generiques pour recommander une prochaine etape sure."
                ),
            )
        reasoning = (
            "Les signaux recuperes restent trop generiques pour proposer un diagnostic exploitable."
            if lang == "fr"
            else "The retrieved signals stay too generic to propose a useful diagnostic."
        )
        return _no_strong_match_payload(
            retrieval,
            query_context=query_context,
            lang=lang,
            reasoning=reasoning,
            filtered_weak_match=False,
            action_relevance_score=0.0,
        )

    support = _supporting_evidence(primary, buckets, selected_cluster_id=selected_cluster_id)
    agreement_count = _action_agreement_count(primary, support)
    root_cause, root_problem_ref = build_root_cause(
        retrieval,
        primary=primary,
        support=support,
        query_context=query_context,
        selected_cluster_id=selected_cluster_id,
    )
    source_label = str(retrieval.get("source") or "fallback_rules")
    if tentative and primary.action_text and agreement_count >= 2 and not primary.domain_mismatch and not primary.topic_mismatch:
        tentative = False
    recommendation_mode = _recommendation_mode(primary, tentative=tentative)
    candidate_action = primary.action_text or primary.excerpt
    supporting_context = build_supporting_context(query_context, recommended_action=candidate_action, lang=lang)
    why_this_matches = build_match_explanation(
        query_context,
        primary=primary,
        support=support,
        root_problem_ref=root_problem_ref,
        root_cause=root_cause,
        lang=lang,
    )
    match_summary = _match_summary(query_context, primary, support, lang=lang) or (why_this_matches[0] if why_this_matches else None)
    evidence_sources = _build_evidence_sources(
        query_context,
        support,
        primary_action=candidate_action,
        lang=lang,
        root_problem_ref=root_problem_ref,
        root_cause=root_cause,
    )
    grounded_action_steps = build_grounded_actions(
        query_context,
        primary=primary,
        support=support,
        probable_root_cause=root_cause,
        lang=lang,
        tentative=tentative,
    )
    retrieval["grounded_action_steps"] = _serialize_action_steps(grounded_action_steps)
    weak_kb_template_seed = (
        primary.evidence_type == "KB article"
        and not grounded_action_steps
        and tentative
        and primary.relevance < ADVISOR_CAUSE_CONFIRMATION["supported_excerpt_relevance"]
        and primary.context_score < ADVISOR_CAUSE_CONFIRMATION["supported_excerpt_context_strong"]
        and primary.exact_focus_hits == 0
        and primary.exact_strong_hits == 0
    )
    if weak_kb_template_seed:
        reasoning = (
            "The retrieved KB guidance does not align closely enough with the current ticket to show a safe action."
            if lang == "en"
            else "La guidance issue de la base de connaissances ne s'aligne pas assez avec le ticket courant pour afficher une action sure."
        )
        return _no_strong_match_payload(
            retrieval,
            query_context=query_context,
            lang=lang,
            reasoning=reasoning,
            filtered_weak_match=False,
            action_relevance_score=0.0,
        )
    if grounded_action_steps:
        candidate_action = grounded_action_steps[0].text
    confidence = _confidence_score(
        primary,
        support=support,
        tentative=tentative,
        source_label=source_label,
        agreement_count=agreement_count,
    )
    if _query_has_signals and selected_cluster_id and any(candidate.cluster_id != selected_cluster_id for candidate in support):
        reasoning = (
            "L'evidence retenue n'a pas pu etre contenue dans une seule famille d'incident, donc aucune action n'est proposee."
            if lang == "fr"
            else "The supporting evidence could not be contained within one incident family, so no action is proposed."
        )
        conflict_checks = _conflict_next_checks(query_context, candidate_clusters[:2], lang=lang)
        return _low_trust_incident_fallback_payload(
            retrieval,
            query_context=query_context,
            lang=lang,
            reasoning=reasoning,
            next_best_actions=conflict_checks,
            validation_steps=conflict_checks[:2],
            concurrent_families=_extract_concurrent_families(candidate_clusters),
        )
    alignment = enforce_action_alignment(
        query_context,
        primary=primary,
        support=support,
        recommended_action=candidate_action,
        agreement_count=agreement_count,
    )
    action_relevance_score = alignment["action_relevance_score"]
    weak_family_support = (
        primary.relevance < ADVISOR_CAUSE_CONFIRMATION["supported_excerpt_relevance"]
        and primary.context_score < 0.24
        and primary.strong_overlap < ADVISOR_CAUSE_CONFIRMATION["supported_excerpt_overlap"]
        and primary.exact_strong_hits == 0
        and agreement_count < 2
    )
    generic_action_without_anchor = (
        action_is_too_generic(candidate_action or "", query_context)
        and primary.exact_focus_hits == 0
        and primary.exact_strong_hits == 0
        and primary.context_score < 0.2
        and primary.relevance < ADVISOR_ALIGNMENT_THRESHOLDS["action_relevance"]
    )
    weak_service_request_match = (
        query_category == "service_request"
        and weak_family_support
        and primary.exact_focus_hits == 0
        and primary.exact_strong_hits == 0
    )
    if low_signal_query and (
        weak_family_support
        or (not grounded_action_steps and action_is_too_generic(candidate_action or "", query_context))
    ):
        return _insufficient_evidence_payload(
            retrieval,
            query_context=query_context,
            lang=lang,
            reasoning=(
                "The selected evidence stays too generic to recommend a safe next step."
                if lang == "en"
                else "Les preuves retenues restent trop generiques pour recommander une prochaine etape sure."
            ),
            conflicting_clusters=candidate_clusters if len(candidate_clusters) >= 2 else None,
        )
    if generic_action_without_anchor or weak_service_request_match:
        return _insufficient_evidence_payload(
            retrieval,
            query_context=query_context,
            lang=lang,
            reasoning=(
                "The retrieved historical action is too generic and weakly aligned to reuse safely."
                if lang == "en"
                else "L'action historique recuperee est trop generique et trop faiblement alignee pour etre reutilisee en securite."
            ),
            conflicting_clusters=candidate_clusters if len(candidate_clusters) >= 2 else None,
        )
    hard_mismatch = action_relevance_score < ADVISOR_ALIGNMENT_THRESHOLDS["hard_action_relevance"] and (
        primary.domain_mismatch
        or primary.topic_mismatch
        or (primary.strong_overlap < 0.1 and primary.exact_strong_hits == 0 and primary.lexical_overlap < 0.12)
    )
    filtered_weak_match = hard_mismatch or (
        confidence < ADVISOR_ALIGNMENT_THRESHOLDS["low_confidence"]
        and action_relevance_score < ADVISOR_ALIGNMENT_THRESHOLDS["action_relevance"]
    )
    if not grounded_action_steps and (
        low_signal_query
        or candidate_action is None
        or action_is_too_generic(candidate_action or "", query_context)
        or tentative
        or weak_family_support
        or alignment["downgrade_to_tentative"]
        or not alignment["resolution_pattern_match"]
    ):
        if low_signal_query or weak_family_support:
            return _insufficient_evidence_payload(
                retrieval,
                query_context=query_context,
                lang=lang,
                reasoning=(
                    "The selected incident family stays too weak or generic to recommend a safe next step."
                    if lang == "en"
                    else "La famille d'incident retenue reste trop faible ou trop generique pour recommander une prochaine etape sure."
                ),
                conflicting_clusters=candidate_clusters if len(candidate_clusters) >= 2 else None,
            )
        reasoning = (
            "The selected incident family is coherent, but the evidence does not support one concrete action strongly enough yet."
            if lang == "en"
            else "La famille d'incident selectionnee reste coherente, mais les preuves ne soutiennent pas encore une action concrete de maniere suffisante."
        )
        return _fallback_diagnostic_payload(
            retrieval,
            query_context=query_context,
            lang=lang,
            reasoning=reasoning,
            filtered_weak_match=filtered_weak_match,
            action_relevance_score=action_relevance_score,
            probable_root_cause=root_cause,
            supporting_context=supporting_context,
            why_this_matches=why_this_matches,
            match_summary=match_summary,
            incident_cluster=incident_cluster,
            impact_summary=impact_summary,
            evidence_sources=evidence_sources,
            action_steps=grounded_action_steps,
        )

    if not alignment["symptom_match"] or not alignment["component_match"]:
        if filtered_weak_match and (primary.domain_mismatch or primary.topic_mismatch):
            reasoning = (
                "Les preuves recuperees pointent vers une autre famille ou une autre couche systeme; aucune action sure n'est affichee."
                if lang == "fr"
                else "The retrieved evidence points to a different incident family or system layer, so no safe action is shown."
            )
            return _no_strong_match_payload(
                retrieval,
                query_context=query_context,
                lang=lang,
                reasoning=reasoning,
                filtered_weak_match=True,
                action_relevance_score=action_relevance_score,
            )
        if filtered_weak_match:
            reasoning = (
                "L'action historique a ete rejetee parce qu'elle ne correspond pas au bon symptome ou a la bonne couche systeme; une verification sure, derivee du ticket, est renvoyee."
                if lang == "fr"
                else "The historical action was rejected because it does not match the right symptom or system layer, so a safe ticket-specific diagnostic is returned."
            )
            return _fallback_diagnostic_payload(
                retrieval,
                query_context=query_context,
                lang=lang,
                reasoning=reasoning,
                filtered_weak_match=True,
                action_relevance_score=action_relevance_score,
                probable_root_cause=root_cause,
                supporting_context=supporting_context,
                why_this_matches=why_this_matches,
                match_summary=match_summary,
                incident_cluster=incident_cluster,
                impact_summary=impact_summary,
                evidence_sources=evidence_sources,
                action_steps=grounded_action_steps,
            )
        reasoning = (
            "Les preuves recuperees ne confirment pas assez le meme symptome et le meme composant; aucune action sure n'est affichee."
            if lang == "fr"
            else "The retrieved evidence does not confirm the same symptom and system layer strongly enough, so no safe action is shown."
        )
        return _no_strong_match_payload(
            retrieval,
            query_context=query_context,
            lang=lang,
            reasoning=reasoning,
            filtered_weak_match=filtered_weak_match,
            action_relevance_score=action_relevance_score,
        )

    if tentative or filtered_weak_match or alignment["downgrade_to_tentative"] or not alignment["resolution_pattern_match"]:
        if filtered_weak_match:
            reasoning = (
                "L'action historique a ete degradee en diagnostic prudent car elle ne passe pas les garde-fous de pertinence ou de couche systeme."
                if lang == "fr"
                else "The historical action was downgraded to a cautious diagnostic because it did not pass the relevance and system-layer guardrails."
            )
        else:
            reasoning = (
                f"L'evidence principale ({primary.evidence_type} {primary.reference}) est partiellement alignee, mais l'accord sur le correctif reste insuffisant."
                if lang == "fr"
                else f"The primary evidence ({primary.evidence_type} {primary.reference}) is partially aligned, but agreement on the fix pattern is still insufficient."
            )
        return _fallback_diagnostic_payload(
            retrieval,
            query_context=query_context,
            lang=lang,
            reasoning=reasoning,
            filtered_weak_match=filtered_weak_match,
            action_relevance_score=action_relevance_score,
            probable_root_cause=root_cause,
            supporting_context=supporting_context,
            why_this_matches=why_this_matches,
            match_summary=match_summary,
            incident_cluster=incident_cluster,
            impact_summary=impact_summary,
            evidence_sources=evidence_sources,
            action_steps=grounded_action_steps,
        )

    recommended_action = grounded_action_steps[0].text if grounded_action_steps else candidate_action
    confidence_band = classify_confidence(confidence)
    confirmed_root_cause = root_cause if (root_problem_ref or confidence >= CONFIDENCE_HIGH_THRESHOLD) else None
    # Use grounded step texts for next_best_actions when available; fall back to
    # the _next_best_actions helper so the list is never empty for evidence_action.
    next_best_actions = [step.text for step in grounded_action_steps[1:]]
    if not next_best_actions:
        next_best_actions = _next_best_actions(
            recommended_action=recommended_action or "",
            probable_root_cause=root_cause,
            tentative=tentative,
            query_context=query_context,
            support=support,
            lang=lang,
        )
    validation_steps = build_validation_from_actions(query_context, action_steps=grounded_action_steps, lang=lang)
    fallback_action = build_fallback_action(
        query_context,
        probable_root_cause=root_cause,
        supporting_context=supporting_context,
        lang=lang,
    )
    primary_step_reason = grounded_action_steps[0].reason if grounded_action_steps else ""
    if lang == "fr":
        reasoning = (
            primary_step_reason
            or f"Action retenue car {primary.reference} recoupe le meme symptome, le meme composant, et la meme logique de correction."
        )
        if agreement_count >= 2 and len(support) > 1:
            reasoning += f" Le chemin de resolution est aussi confirme par {support[1].reference}."
        if root_cause:
            reasoning += f" Cause racine probable: {root_cause}."
    else:
        reasoning = (
            primary_step_reason
            or f"Selected because {primary.reference} matches the same symptom, the same system layer, and the same fix pattern."
        )
        if agreement_count >= 2 and len(support) > 1:
            reasoning += f" The fix path is also confirmed by {support[1].reference}."
        if root_cause:
            reasoning += f" Probable root cause: {root_cause}."

    response_text = _build_response_text(
        recommended_action=recommended_action,
        reasoning=reasoning,
        confidence=confidence,
        evidence_sources=evidence_sources,
        lang=lang,
        display_mode=_EVIDENCE_ACTION_DISPLAY,
    )

    return {
        "recommended_action": recommended_action,
        "reasoning": reasoning,
        "probable_root_cause": root_cause,
        "root_cause": confirmed_root_cause,
        "supporting_context": supporting_context,
        "why_this_matches": why_this_matches,
        "evidence_sources": evidence_sources,
        "tentative": tentative,
        "confidence": confidence,
        "confidence_band": confidence_band,
        "confidence_label": confidence_band,
        "source_label": source_label,
        "recommendation_mode": recommendation_mode,
        "match_summary": match_summary,
        "next_best_actions": next_best_actions,
        "incident_cluster": incident_cluster,
        "impact_summary": impact_summary,
        "filtered_weak_match": False,
        "action_relevance_score": action_relevance_score,
        "mode": _EVIDENCE_ACTION_DISPLAY,
        "display_mode": _EVIDENCE_ACTION_DISPLAY,
        "validation_steps": validation_steps,
        "workflow_steps": [step.text for step in grounded_action_steps],
        "action_steps": _serialize_action_steps(grounded_action_steps),
        "fallback_action": fallback_action,
        "response_text": response_text,
    }
