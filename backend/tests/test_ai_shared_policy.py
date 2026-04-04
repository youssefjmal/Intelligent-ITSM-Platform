from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.ai.chat_payloads import _likelihood_from_score, _validation_steps_in_scope
from app.services.ai.feedback import _confidence_band_from_row
from app.services.ai.prompt_policy import CHAT_KNOWLEDGE_FIRST_POLICY, GROUNDED_FORMATTER_POLICY
from app.services.ai.prompts import build_chat_grounded_prompt, build_chat_prompt
from app.services.ai.resolver import build_resolution_advice_model
from app.services.ai.topic_templates import topic_grounded_action_templates, topic_validation_actions


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.81, "high"),
        (0.6, "medium"),
        (0.18, "low"),
    ],
)
def test_shared_confidence_policy_is_consistent_across_layers(score: float, expected: str) -> None:
    advice = build_resolution_advice_model(
        {
            "recommended_action": "Verify the affected workflow.",
            "reasoning": "Evidence aligns on the same workflow.",
            "confidence": score,
        },
        lang="en",
    )

    assert advice is not None
    assert advice.confidence_band == expected
    assert _likelihood_from_score(score) == expected
    assert _confidence_band_from_row(SimpleNamespace(context_json={}, confidence_snapshot=score)) == expected


def test_chat_payload_family_scoping_uses_shared_taxonomy() -> None:
    resolver_output = SimpleNamespace(
        retrieval={
            "evidence_clusters": {
                "selected_cluster_id": "payroll_export",
                "clusters": [
                    {
                        "cluster_id": "payroll_export",
                        "dominant_topic": "payroll_export",
                    }
                ],
            }
        },
        validation_steps=[
            "Generate one control export and validate the corrected date columns in the downstream import.",
            "Send one controlled approval notice and confirm it reaches the expected manager recipient.",
        ],
    )

    assert _validation_steps_in_scope(resolver_output, limit=3) == [
        "Generate one control export and validate the corrected date columns in the downstream import."
    ]


def test_topic_template_registry_exposes_expected_family_actions() -> None:
    crm_actions = topic_grounded_action_templates("crm_integration", lang="en")
    payroll_validation = topic_validation_actions("payroll_export", lang="en")

    assert crm_actions
    assert "crm integration token" in crm_actions[0].lower()
    assert payroll_validation
    assert any("date" in step.lower() for step in payroll_validation)


def test_prompt_builders_include_shared_policy_fragments() -> None:
    chat_prompt = build_chat_prompt(
        question="What should I do for TW-MOCK-019?",
        knowledge_section="Knowledge Section:\n[TEAM-1] CRM worker token reused stale credential.\n",
        lang="en",
        greeting="Hello",
        assignee_list=["Amina"],
        stats={"open": 2},
        top_tickets=["TW-MOCK-019"],
    )
    grounded_prompt = build_chat_grounded_prompt(
        question="Why is this happening?",
        grounding={"mode": "tentative_diagnostic"},
        lang="en",
        greeting="Hello",
    )

    assert CHAT_KNOWLEDGE_FIRST_POLICY.strip() in chat_prompt
    assert GROUNDED_FORMATTER_POLICY.strip() in grounded_prompt
