from __future__ import annotations

from app.models.enums import TicketCategory, TicketPriority
from app.services.ai.classifier import _infer_classification_from_strong_matches


def test_infer_classification_from_strong_matches_prefers_weighted_consensus() -> None:
    strong_matches = [
        {
            "score": 0.92,
            "metadata": {
                "priority": "High",
                "issuetype": "Report an Incident",
                "components": "SMTP Gateway",
                "labels": "mailing,outbox,delivery",
            },
        },
        {
            "score": 0.87,
            "metadata": {
                "priority": "High",
                "issuetype": "Incident",
                "components": "Email Service",
                "labels": "smtp,queue",
            },
        },
        {
            "score": 0.78,
            "metadata": {
                "priority": "Medium",
                "issuetype": "Service Request",
                "components": "Application",
                "labels": "portal",
            },
        },
    ]

    priority, category = _infer_classification_from_strong_matches(strong_matches)
    assert priority == TicketPriority.high
    assert category == TicketCategory.email


def test_infer_classification_from_strong_matches_returns_none_when_no_consensus() -> None:
    strong_matches = [
        {"score": 0.80, "metadata": {"priority": "High", "issuetype": "Network Incident", "labels": "vpn"}},
        {"score": 0.80, "metadata": {"priority": "Low", "issuetype": "Hardware Incident", "labels": "printer"}},
    ]

    priority, category = _infer_classification_from_strong_matches(strong_matches)
    assert priority is None
    assert category is None
