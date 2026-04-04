from __future__ import annotations

from app.models.enums import TicketCategory, TicketPriority, TicketType
from app.services.ai.classifier import (
    _infer_classification_from_strong_matches,
    _load_strong_similarity_matches,
    apply_category_guardrail,
)
from app.services.ai import classifier


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

    priority, category, ticket_type = _infer_classification_from_strong_matches(strong_matches)
    assert priority == TicketPriority.high
    assert category == TicketCategory.email
    assert ticket_type == TicketType.incident


def test_infer_classification_from_strong_matches_returns_none_when_no_consensus() -> None:
    strong_matches = [
        {"score": 0.80, "metadata": {"priority": "High", "issuetype": "Network Incident", "labels": "vpn"}},
        {"score": 0.80, "metadata": {"priority": "Low", "issuetype": "Hardware Incident", "labels": "printer"}},
    ]

    priority, category, ticket_type = _infer_classification_from_strong_matches(strong_matches)
    assert priority is None
    assert category is None
    assert ticket_type == TicketType.incident


def test_apply_category_guardrail_prefers_dominant_context_over_false_positive_domain_mentions() -> None:
    category = apply_category_guardrail(
        "RAG retrieval returns wrong mail certificate tickets for VPN incidents",
        (
            "The AI retrieval pipeline returns mail relay certificate incidents when agents investigate VPN access failures. "
            "Investigation points to embedding similarity drift and cross-domain grounding in the application pipeline."
        ),
        TicketCategory.email,
    )

    assert category == TicketCategory.application


def test_apply_category_guardrail_prefers_application_for_retrieval_meta_ticket() -> None:
    category = apply_category_guardrail(
        "KB semantic search returning unrelated tickets for VPN queries",
        (
            "The RAG retrieval pipeline is returning mail/email chunks as the top results when agents query about VPN connectivity issues. "
            "The cosine similarity scores for these cross-domain matches are above the retrieval threshold. "
            "Investigation shows the embedding model is conflating certificate signals between VPN TLS certificates and mail relay SSL certificates, "
            "and the context gate should be blocking them."
        ),
        TicketCategory.email,
    )

    assert category == TicketCategory.application


def test_load_strong_similarity_matches_filters_conflicting_cross_domain_semantic_hits(monkeypatch) -> None:
    monkeypatch.setattr(
        classifier,
        "search_kb_issues",
        lambda db, query, top_k: [
            {
                "jira_key": "APP-1",
                "score": 0.87,
                "content": "Embedding retrieval mismatch in the AI pipeline after similarity drift.",
                "metadata": {
                    "summary": "AI retrieval mismatch after similarity drift",
                    "issuetype": "Bug",
                    "components": "AI Platform",
                    "labels": "embedding,retrieval,pipeline",
                },
            },
            {
                "jira_key": "MAIL-1",
                "score": 0.88,
                "content": "Mail relay delivery deferred after certificate renewal.",
                "metadata": {
                    "summary": "Mail relay deferred after certificate renewal",
                    "issuetype": "Service Request",
                    "components": "Email Service",
                    "labels": "smtp,relay,certificate",
                },
            },
        ],
    )

    matches = _load_strong_similarity_matches(
        "RAG retrieval returns wrong mail certificate tickets for VPN incidents",
        (
            "The application retrieval pipeline is surfacing email incidents as false positives. "
            "Investigate cross-domain grounding and embedding similarity drift."
        ),
        db=None,
    )

    assert matches == []
