"""Shared LLM refinement helpers for low-trust and fulfillment actions."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any

from app.services.ai.llm import extract_json, ollama_generate
from app.services.ai.prompts import (
    build_llm_fallback_action_prompt,
    build_service_request_refinement_prompt,
)

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_\-]{2,}", re.IGNORECASE)
_ID_RE = re.compile(r"\b(?:TW|PB|KB|INC|REQ|TASK|JIRA|TEAMWILL)-[A-Z0-9\-]+\b", re.IGNORECASE)
_CONFIRMED_TONE_PATTERNS = (
    re.compile(r"\bconfirmed\b", re.IGNORECASE),
    re.compile(r"\bdefinitely\b", re.IGNORECASE),
    re.compile(r"\broot cause is\b", re.IGNORECASE),
    re.compile(r"\bresolved by\b", re.IGNORECASE),
    re.compile(r"\bfixed by\b", re.IGNORECASE),
    re.compile(r"\bwill resolve\b", re.IGNORECASE),
)
_SERVICE_REQUEST_DIAGNOSTIC_PATTERNS = (
    re.compile(r"\broot cause\b", re.IGNORECASE),
    re.compile(r"\boutage\b", re.IGNORECASE),
    re.compile(r"\berror\b", re.IGNORECASE),
    re.compile(r"\bfailure\b", re.IGNORECASE),
    re.compile(r"\brestart\b", re.IGNORECASE),
    re.compile(r"\brollback\b", re.IGNORECASE),
)
_GENERIC_PHRASES = (
    "follow the process",
    "follow the procedure",
    "handle the request",
    "complete the task",
    "check the system",
    "review the request",
    "follow best practices",
    "take the necessary action",
    "ensure everything is correct",
)
_LOW_TRUST_POSITIONING_PATTERNS = (
    re.compile(r"\btypically\b", re.IGNORECASE),
    re.compile(r"\bmay\b", re.IGNORECASE),
    re.compile(r"\bcan indicate\b", re.IGNORECASE),
    re.compile(r"\bcommonly\b", re.IGNORECASE),
)
_GENERIC_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "ticket",
        "request",
        "task",
        "action",
        "follow",
        "process",
        "procedure",
        "check",
        "review",
        "verify",
        "confirm",
        "ensure",
    }
)


@dataclass(slots=True)
class LLMActionPackage:
    recommended_action: str
    next_best_actions: list[str]
    validation_steps: list[str]
    reasoning_note: str | None = None


def _normalize_line(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_lines(values: list[Any] | None, *, limit: int) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        normalized = _normalize_line(value)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        rows.append(normalized)
        if len(rows) >= limit:
            break
    return rows


def _package_text(package: LLMActionPackage) -> str:
    return " ".join(
        [
            package.recommended_action,
            *package.next_best_actions,
            *package.validation_steps,
            package.reasoning_note or "",
        ]
    ).strip()


def _content_tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN_RE.findall(text or "")
        if token.casefold() not in _GENERIC_STOPWORDS
    }


def _specificity_score(*texts: str) -> float:
    tokens = set().union(*(_content_tokens(text) for text in texts if text))
    return float(len(tokens))


def _looks_generic(text: str) -> bool:
    normalized = _normalize_line(text).casefold()
    if not normalized:
        return True
    if normalized in _GENERIC_PHRASES:
        return True
    if any(phrase in normalized for phrase in _GENERIC_PHRASES):
        return True
    return len(_content_tokens(normalized)) <= 3


def _contains_unapproved_reference(text: str, *, allowed_text: str) -> bool:
    if not text:
        return False
    allowed_ids = set(_ID_RE.findall(allowed_text or ""))
    for value in set(_ID_RE.findall(text)):
        if value not in allowed_ids:
            return True
    return False


def _has_confirmed_tone(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _CONFIRMED_TONE_PATTERNS)


def _repeats_attempted_steps(package: LLMActionPackage, attempted_steps: list[str]) -> bool:
    if not attempted_steps:
        return False
    attempted = [_normalize_line(step).casefold() for step in attempted_steps if _normalize_line(step)]
    if not attempted:
        return False
    for row in [package.recommended_action, *package.next_best_actions, *package.validation_steps]:
        lowered = _normalize_line(row).casefold()
        if not lowered:
            continue
        if any(step in lowered or lowered in step for step in attempted):
            return True
    return False


def _parse_action_package(raw: str) -> LLMActionPackage | None:
    if not raw:
        return None
    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        return None
    recommended_action = _normalize_line(parsed.get("recommended_action"))
    next_best_actions = _normalize_lines(parsed.get("next_best_actions"), limit=4)
    validation_steps = _normalize_lines(parsed.get("validation_steps"), limit=3)
    reasoning_note = _normalize_line(parsed.get("reasoning_note")) or None
    if not recommended_action:
        return None
    if not next_best_actions and not validation_steps:
        return None
    return LLMActionPackage(
        recommended_action=recommended_action,
        next_best_actions=next_best_actions,
        validation_steps=validation_steps,
        reasoning_note=reasoning_note,
    )


def _call_action_refiner(system_prompt: str, user_prompt: str) -> LLMActionPackage | None:
    try:
        raw = ollama_generate(f"{system_prompt}\n\n{user_prompt}", json_mode=True)
    except Exception:  # noqa: BLE001
        log.warning("LLM action refiner call failed", exc_info=True)
        return None
    return _parse_action_package(raw)


def _validate_low_trust_positioning(package: LLMActionPackage) -> bool:
    text = _package_text(package)
    if _has_confirmed_tone(text):
        return False
    reasoning = _normalize_line(package.reasoning_note)
    if reasoning and not any(pattern.search(reasoning) for pattern in _LOW_TRUST_POSITIONING_PATTERNS):
        return False
    return True


def generate_low_trust_incident_actions(
    *,
    ticket_title: str,
    ticket_description: str,
    ticket_category: str,
    ticket_priority: str,
    attempted_steps: list[str],
    concurrent_families: list[str],
    deterministic_fallback: str | None,
    language: str = "fr",
) -> LLMActionPackage | None:
    """Generate a low-trust action package for no-strong-match incident cases."""

    system_prompt, user_prompt = build_llm_fallback_action_prompt(
        ticket_title=ticket_title,
        ticket_description=ticket_description,
        ticket_category=ticket_category,
        ticket_priority=ticket_priority,
        attempted_steps=attempted_steps,
        concurrent_families=concurrent_families,
        deterministic_fallback=deterministic_fallback,
        language=language,
    )
    package = _call_action_refiner(system_prompt, user_prompt)
    if package is None:
        return None

    allowed_text = " ".join([ticket_title, ticket_description, deterministic_fallback or "", *attempted_steps, *concurrent_families])
    package_text = _package_text(package)
    if _contains_unapproved_reference(package_text, allowed_text=allowed_text):
        return None
    if _repeats_attempted_steps(package, attempted_steps):
        return None
    if not _validate_low_trust_positioning(package):
        return None

    fallback_specificity = _specificity_score(deterministic_fallback or "")
    package_specificity = _specificity_score(package.recommended_action, *package.next_best_actions, *package.validation_steps)
    if package_specificity < max(4.0, fallback_specificity):
        return None
    if _looks_generic(package.recommended_action) and package_specificity <= fallback_specificity + 1.0:
        return None
    return package


def refine_service_request_actions(
    *,
    ticket_title: str,
    ticket_description: str,
    profile_metadata: dict[str, Any],
    base_recommended_action: str,
    base_next_best_actions: list[str],
    base_validation_steps: list[str],
    language: str = "fr",
) -> LLMActionPackage | None:
    """Refine deterministic service-request actions without changing workflow intent."""

    system_prompt, user_prompt = build_service_request_refinement_prompt(
        ticket_title=ticket_title,
        ticket_description=ticket_description,
        profile_metadata=profile_metadata,
        base_recommended_action=base_recommended_action,
        base_next_best_actions=base_next_best_actions,
        base_validation_steps=base_validation_steps,
        language=language,
    )
    package = _call_action_refiner(system_prompt, user_prompt)
    if package is None:
        return None

    allowed_text = " ".join(
        [
            ticket_title,
            ticket_description,
            base_recommended_action,
            *base_next_best_actions,
            *base_validation_steps,
            *[str(item) for item in list((profile_metadata or {}).get("target_terms") or [])],
        ]
    )
    package_text = _package_text(package)
    if _contains_unapproved_reference(package_text, allowed_text=allowed_text):
        return None
    if _has_confirmed_tone(package_text):
        return None
    if any(pattern.search(package_text) for pattern in _SERVICE_REQUEST_DIAGNOSTIC_PATTERNS):
        return None

    base_specificity = _specificity_score(base_recommended_action, *base_next_best_actions, *base_validation_steps)
    package_specificity = _specificity_score(package.recommended_action, *package.next_best_actions, *package.validation_steps)
    if package_specificity < max(5.0, base_specificity - 1.0):
        return None
    if _looks_generic(package.recommended_action) and package_specificity <= base_specificity:
        return None

    try:
        from app.services.ai.service_requests import (
            ServiceRequestProfile,
            build_service_request_profile,
            service_request_profile_similarity,
        )

        base_profile = ServiceRequestProfile(
            family=str((profile_metadata or {}).get("family") or "").strip() or None,
            operation=str((profile_metadata or {}).get("operation") or "").strip() or None,
            resource=str((profile_metadata or {}).get("resource") or "").strip() or None,
            governance=tuple(str(item).strip() for item in list((profile_metadata or {}).get("governance") or []) if str(item).strip()),
            target_terms=tuple(str(item).strip() for item in list((profile_metadata or {}).get("target_terms") or []) if str(item).strip()),
            incident_conflict_score=float((profile_metadata or {}).get("incident_conflict_score") or 0.0),
            confidence=float((profile_metadata or {}).get("confidence") or 0.0),
        )
        refined_profile = build_service_request_profile(
            package.recommended_action,
            " ".join([*package.next_best_actions, *package.validation_steps]),
        )
        if base_profile.family and refined_profile.family and refined_profile.family != base_profile.family:
            if service_request_profile_similarity(base_profile, refined_profile) < 0.55:
                return None
        if refined_profile.incident_conflict_score >= 1.0 and base_profile.confidence >= 0.6:
            return None
    except Exception:  # noqa: BLE001
        log.warning("Service-request action refinement validation failed", exc_info=True)
        return None

    return package
