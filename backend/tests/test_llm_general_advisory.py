"""
Tests for the LLM general-knowledge advisory fallback introduced in
build_llm_general_advisory() (resolution_advisor.py).

Coverage:
  1. Happy path — valid JSON returned by LLM → LLMGeneralAdvisory populated.
  2. LLM unavailable (exception) → returns None, never raises.
  3. Invalid JSON from LLM → returns None, never raises.
  4. Attempted steps are removed from suggested_checks.
  5. Confidence is ALWAYS LLM_GENERAL_ADVISORY_CONFIDENCE (0.25).
  6. probable_causes list is capped at 3 items.
  7. suggested_checks list is capped at 4 items.
  8. Empty probable_causes list accepted.
  9. Empty suggested_checks list accepted.
 10. display_mode promoted to llm_general_knowledge in build_resolution_advice
     when primary is None and LLM advisory succeeds.
 11. display_mode stays no_strong_match when LLM advisory returns None.
 12. knowledge_source field set to "llm_general_knowledge" on advisory object.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_LLM_RESPONSE = json.dumps(
    {
        "probable_causes": ["Cause A", "Cause B", "Cause C", "Cause D (excess)"],
        "suggested_checks": [
            "Check 1",
            "Check 2",
            "Check 3",
            "Check 4",
            "Check 5 (excess)",
        ],
        "escalation_hint": None,
    }
)

_VALID_LLM_RESPONSE_WITH_ESCALATION = json.dumps(
    {
        "probable_causes": ["Root cause X"],
        "suggested_checks": ["Restart the service", "Check disk space"],
        "escalation_hint": "Escalate if unresolved after 30 minutes.",
    }
)


def _make_advisory(**kwargs):
    """Return a LLMGeneralAdvisory populated with build_llm_general_advisory()."""
    from app.services.ai.resolution_advisor import build_llm_general_advisory

    defaults = dict(
        ticket_title="VPN not connecting",
        ticket_description="User cannot connect to VPN since yesterday.",
        ticket_category="network",
        ticket_priority="high",
        attempted_steps=[],
        concurrent_families=[],
        language="fr",
    )
    defaults.update(kwargs)
    return build_llm_general_advisory(**defaults)


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_happy_path_returns_advisory():
    """Valid LLM JSON → advisory is populated with all expected fields."""
    with patch(
        "app.services.ai.llm.ollama_generate",
        return_value=_VALID_LLM_RESPONSE,
    ):
        result = _make_advisory()

    assert result is not None
    assert result.probable_causes == ["Cause A", "Cause B", "Cause C"]
    assert result.suggested_checks == ["Check 1", "Check 2", "Check 3", "Check 4"]


# ---------------------------------------------------------------------------
# 2. LLM unavailable — should return None, not raise
# ---------------------------------------------------------------------------


def test_llm_unavailable_returns_none():
    """When ollama_generate raises, build_llm_general_advisory returns None."""
    with patch(
        "app.services.ai.llm.ollama_generate",
        side_effect=ConnectionError("Ollama offline"),
    ):
        result = _make_advisory()

    assert result is None


# ---------------------------------------------------------------------------
# 3. Invalid JSON — returns None, does not raise
# ---------------------------------------------------------------------------


def test_invalid_json_returns_none():
    """When ollama_generate returns non-JSON garbage, function returns None."""
    with patch(
        "app.services.ai.llm.ollama_generate",
        return_value="<error>not json</error>",
    ):
        result = _make_advisory()

    assert result is None


# ---------------------------------------------------------------------------
# 4. Attempted steps are excluded from suggested_checks
# ---------------------------------------------------------------------------


def test_attempted_steps_excluded():
    """Steps the agent already tried must not appear in suggested_checks."""
    llm_response = json.dumps(
        {
            "probable_causes": ["Memory leak"],
            "suggested_checks": [
                "Restart the service",
                "Check error logs",
                "Verify disk space",
            ],
            "escalation_hint": None,
        }
    )
    with patch(
        "app.services.ai.llm.ollama_generate",
        return_value=llm_response,
    ):
        result = _make_advisory(attempted_steps=["Restart the service"])

    assert result is not None
    assert "Restart the service" not in result.suggested_checks
    assert "Check error logs" in result.suggested_checks
    assert "Verify disk space" in result.suggested_checks


# ---------------------------------------------------------------------------
# 5. Confidence is always LLM_GENERAL_ADVISORY_CONFIDENCE
# ---------------------------------------------------------------------------


def test_confidence_always_fixed():
    """Advisory confidence must always equal the calibration constant (0.25)."""
    from app.services.ai.calibration import LLM_GENERAL_ADVISORY_CONFIDENCE

    with patch(
        "app.services.ai.llm.ollama_generate",
        return_value=_VALID_LLM_RESPONSE,
    ):
        result = _make_advisory()

    assert result is not None
    assert result.confidence == LLM_GENERAL_ADVISORY_CONFIDENCE
    assert result.confidence == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# 6. probable_causes capped at 3
# ---------------------------------------------------------------------------


def test_probable_causes_capped_at_3():
    """More than 3 probable_causes from LLM must be truncated to 3."""
    many_causes = json.dumps(
        {
            "probable_causes": [f"Cause {i}" for i in range(8)],
            "suggested_checks": ["Step 1"],
            "escalation_hint": None,
        }
    )
    with patch(
        "app.services.ai.llm.ollama_generate",
        return_value=many_causes,
    ):
        result = _make_advisory()

    assert result is not None
    assert len(result.probable_causes) == 3


# ---------------------------------------------------------------------------
# 7. suggested_checks capped at 4
# ---------------------------------------------------------------------------


def test_suggested_checks_capped_at_4():
    """More than 4 suggested_checks from LLM must be truncated to 4."""
    many_checks = json.dumps(
        {
            "probable_causes": ["Cause 1"],
            "suggested_checks": [f"Check {i}" for i in range(10)],
            "escalation_hint": None,
        }
    )
    with patch(
        "app.services.ai.llm.ollama_generate",
        return_value=many_checks,
    ):
        result = _make_advisory()

    assert result is not None
    assert len(result.suggested_checks) == 4


# ---------------------------------------------------------------------------
# 8. Empty probable_causes accepted
# ---------------------------------------------------------------------------


def test_empty_probable_causes_accepted():
    """Advisory with empty probable_causes list is valid and returned."""
    response = json.dumps(
        {
            "probable_causes": [],
            "suggested_checks": ["Check network route"],
            "escalation_hint": None,
        }
    )
    with patch(
        "app.services.ai.llm.ollama_generate",
        return_value=response,
    ):
        result = _make_advisory()

    assert result is not None
    assert result.probable_causes == []


# ---------------------------------------------------------------------------
# 9. Empty suggested_checks accepted
# ---------------------------------------------------------------------------


def test_empty_suggested_checks_accepted():
    """Advisory with empty suggested_checks list is valid and returned."""
    response = json.dumps(
        {
            "probable_causes": ["Hardware fault"],
            "suggested_checks": [],
            "escalation_hint": None,
        }
    )
    with patch(
        "app.services.ai.llm.ollama_generate",
        return_value=response,
    ):
        result = _make_advisory()

    assert result is not None
    assert result.suggested_checks == []


# ---------------------------------------------------------------------------
# 10. display_mode promoted to llm_general_knowledge in build_resolution_advice
# ---------------------------------------------------------------------------


def test_display_mode_promoted_when_advisory_succeeds():
    """
    When retrieval produces no primary match and LLM advisory succeeds,
    the returned payload's display_mode must be 'llm_general_knowledge'.

    _has_specific_guidance_context is stubbed to True so that the function
    reaches the _no_strong_match_payload interception at line 3120 rather
    than returning early via _insufficient_evidence_payload.  The LLM
    advisory injection logic is what this test exercises.
    """
    from app.services.ai.resolution_advisor import build_resolution_advice
    from app.services.ai.calibration import DISPLAY_MODE_LLM_GENERAL
    from app.services.ai.action_refiner import LLMActionPackage
    from app.services.ai.resolution_advisor import LLMGeneralAdvisory

    retrieval: dict = {
        "primary": None,
        "candidates": [],
        "candidate_clusters": [],
        "query_context": {
            "title": "VPN issue",
            "description": "Cannot connect",
            "metadata": {"category": "network", "priority": "high"},
        },
        "fallback_reason": "no_candidates",
        "lang": "fr",
    }

    with (
        patch(
            "app.services.ai.resolution_advisor._has_specific_guidance_context",
            return_value=True,
        ),
        patch(
            "app.services.ai.resolution_advisor.generate_low_trust_incident_actions",
            return_value=LLMActionPackage(
                recommended_action="Validate one affected VPN session path before changing the shared policy.",
                next_best_actions=["Compare one affected MFA loop against a healthy session.", "Document any policy drift before broad remediation."],
                validation_steps=["Confirm the loop stops for one affected finance user."],
                reasoning_note="This is low-trust guidance based on general IT knowledge only.",
            ),
        ),
        patch(
            "app.services.ai.resolution_advisor.build_llm_general_advisory",
            return_value=LLMGeneralAdvisory(
                probable_causes=["VPN policy drift can commonly trigger MFA loops."],
                suggested_checks=["Compare an affected route and MFA session against a healthy user."],
                escalation_hint=None,
                knowledge_source="llm_general_knowledge",
                confidence=0.25,
                language="fr",
            ),
        ),
    ):
        payload = build_resolution_advice(retrieval)

    assert payload.get("display_mode") == DISPLAY_MODE_LLM_GENERAL
    assert payload.get("mode") == DISPLAY_MODE_LLM_GENERAL
    assert payload.get("llm_general_advisory") is not None
    assert payload.get("recommended_action")
    assert payload.get("action_refinement_source") == "llm_general_knowledge"


# ---------------------------------------------------------------------------
# 11. display_mode stays no_strong_match when advisory returns None
# ---------------------------------------------------------------------------


def test_display_mode_unchanged_when_advisory_fails():
    """
    When retrieval produces no primary match AND the LLM advisory call fails,
    the payload display_mode must remain 'no_strong_match'.

    _has_specific_guidance_context is stubbed to True for the same reason as
    test_display_mode_promoted_when_advisory_succeeds — to reach line 3120.
    """
    from app.services.ai.resolution_advisor import build_resolution_advice
    from app.services.ai.calibration import DISPLAY_MODE_NO_STRONG_MATCH

    retrieval: dict = {
        "primary": None,
        "candidates": [],
        "candidate_clusters": [],
        "query_context": {
            "title": "VPN issue",
            "description": "Cannot connect",
            "metadata": {"category": "network", "priority": "high"},
        },
        "fallback_reason": "no_candidates",
        "lang": "fr",
    }

    with (
        patch(
            "app.services.ai.resolution_advisor._has_specific_guidance_context",
            return_value=True,
        ),
        patch(
            "app.services.ai.resolution_advisor.generate_low_trust_incident_actions",
            return_value=None,
        ),
        patch(
            "app.services.ai.resolution_advisor.build_llm_general_advisory",
            return_value=None,
        ),
    ):
        payload = build_resolution_advice(retrieval)

    assert payload.get("display_mode") == DISPLAY_MODE_NO_STRONG_MATCH
    assert payload.get("llm_general_advisory") is None
    assert payload.get("action_refinement_source") == "none"


def test_low_trust_llm_fallback_still_runs_when_specific_guidance_context_is_weak():
    from app.services.ai.action_refiner import LLMActionPackage
    from app.services.ai.calibration import DISPLAY_MODE_LLM_GENERAL
    from app.services.ai.resolution_advisor import LLMGeneralAdvisory, build_resolution_advice

    retrieval: dict = {
        "primary": None,
        "candidates": [],
        "candidate_clusters": [],
        "query_context": {
            "title": "API pods entering CrashLoopBackOff after node pool upgrade",
            "description": "Pods restart after the rollout and the best clue is in the ticket comments.",
            "metadata": {"category": "infrastructure", "priority": "critical"},
        },
        "fallback_reason": "no_candidates",
        "lang": "en",
    }

    with (
        patch(
            "app.services.ai.resolution_advisor._has_specific_guidance_context",
            return_value=False,
        ),
        patch(
            "app.services.ai.resolution_advisor.generate_low_trust_incident_actions",
            return_value=LLMActionPackage(
                recommended_action="Validate one crashing pod against the new node defaults before widening the rollout.",
                next_best_actions=[
                    "Compare the failing deployment resource requests against the new node pool defaults.",
                    "Capture one pod describe output and one replica event stream before applying the broader manifest change.",
                ],
                validation_steps=["Confirm one pod stabilizes on staging before continuing the rollout."],
                reasoning_note="This remains low-trust guidance based on general platform operations knowledge.",
            ),
        ),
        patch(
            "app.services.ai.resolution_advisor.build_llm_general_advisory",
            return_value=LLMGeneralAdvisory(
                probable_causes=["Node-pool default changes can surface resource-limit mismatches after rollout."],
                suggested_checks=["Compare one failing pod request/limit pair with the new node defaults."],
                escalation_hint=None,
                knowledge_source="llm_general_knowledge",
                confidence=0.25,
                language="en",
            ),
        ),
    ):
        payload = build_resolution_advice(retrieval, lang="en")

    assert payload is not None
    assert payload.get("display_mode") == DISPLAY_MODE_LLM_GENERAL
    assert payload.get("recommended_action")
    assert payload.get("action_refinement_source") == "llm_general_knowledge"


# ---------------------------------------------------------------------------
# 12. knowledge_source field is correct
# ---------------------------------------------------------------------------


def test_knowledge_source_field():
    """knowledge_source on the returned advisory must be 'llm_general_knowledge'."""
    with patch(
        "app.services.ai.llm.ollama_generate",
        return_value=_VALID_LLM_RESPONSE,
    ):
        result = _make_advisory()

    assert result is not None
    assert result.knowledge_source == "llm_general_knowledge"
