from __future__ import annotations

from app.services.ai.retrieval import (
    _retrieval_consensus,
    _context_metrics,
    _passes_context_gate,
    _query_context,
    cluster_evidence,
    grounded_issue_matches,
    select_primary_cluster,
)


def test_context_gate_rejects_mail_transport_candidate_for_crm_sync_query() -> None:
    query_context = _query_context(
        "CRM sync job stalls after token rotation\n"
        "The scheduled CRM sync starts on time, but it stalls after token rotation and never writes the latest contact updates.\n"
        "category=infrastructure"
    )
    metrics = _context_metrics(
        query_context,
        candidate_text="Resolved by updating the relay certificate chain and clearing the deferred transport queue.",
        candidate_title="Mail relay delivery deferred after certificate renewal",
        category_hint="email",
    )

    assert metrics["topic_mismatch"] is True
    assert metrics["strong_overlap"] < 0.12
    assert _passes_context_gate(metrics, semantic_score=0.78) is False


def test_context_gate_keeps_mail_transport_candidate_for_mail_ticket() -> None:
    query_context = _query_context(
        "Ticket notifications fail after relay certificate renewal\n"
        "Outbound delivery freezes after the relay certificate update and deferred emails stay queued.\n"
        "category=email"
    )
    metrics = _context_metrics(
        query_context,
        candidate_text="Resolved by updating the relay certificate chain and clearing the deferred transport queue.",
        candidate_title="Mail relay delivery deferred after certificate renewal",
        category_hint="email",
    )

    assert metrics["topic_mismatch"] is False
    assert metrics["strong_overlap"] >= 0.12
    assert _passes_context_gate(metrics, semantic_score=0.78) is True


def test_query_context_marks_false_positive_domain_as_negative_signal() -> None:
    query_context = _query_context(
        "RAG retrieval returns wrong mail certificate tickets for VPN incidents\n"
        "The assistant keeps surfacing email relay incidents as false positives while agents troubleshoot VPN access failures.\n"
        "category=network"
    )
    metrics = _context_metrics(
        query_context,
        candidate_text="Resolved by updating the relay certificate chain and clearing the deferred transport queue.",
        candidate_title="Mail relay delivery deferred after certificate renewal",
        category_hint="email",
    )

    assert "network" in query_context["domains"]
    assert "email" in query_context["negative_domains"]
    assert "mail_transport" in query_context["negative_topics"]
    assert metrics["contrast_domain_match"] is True
    assert metrics["contrast_topic_match"] is True
    assert _passes_context_gate(metrics, semantic_score=0.84) is False


def test_query_context_preserves_query_target_for_retrieval_meta_ticket() -> None:
    query_context = _query_context(
        "KB semantic search returning unrelated tickets for VPN queries\n"
        "The RAG retrieval pipeline is returning mail/email chunks as the top results when agents query about VPN connectivity issues. "
        "The cosine similarity scores for these cross-domain matches are above the retrieval threshold.\n"
        "category=application"
    )

    assert "application" in query_context["domains"]
    assert "network" in query_context["domains"]
    assert "email" in query_context["negative_domains"]
    assert "mail_transport" in query_context["negative_topics"]
    assert "ai_ml_pipeline" in query_context["topics"]
    assert "network_access" in query_context["topics"]


def test_cluster_evidence_prefers_strong_domain_overlap_over_generic_rotation_overlap() -> None:
    query_context = _query_context(
        "CRM sync job stalls after token rotation\n"
        "The scheduled CRM sync starts on time, but it stalls after token rotation and never writes the latest contact updates.\n"
        "category=infrastructure"
    )
    crm_metrics = _context_metrics(
        query_context,
        candidate_text="Reload the CRM worker token cache, restart the sync worker, and requeue the stalled contacts.",
        candidate_title="CRM worker stalled after token cache rotation",
        category_hint="infrastructure",
    )
    generic_metrics = _context_metrics(
        query_context,
        candidate_text="Create a weekly dashboard service rotation review task and update the tracker.",
        candidate_title="Create weekly dashboard rotation review task",
        category_hint="application",
    )

    clustered = cluster_evidence(
        query_context,
        [
            {
                "reference": "TW-CRM-1",
                "title": "CRM worker stalled after token cache rotation",
                "text": "Reload the CRM worker token cache, restart the sync worker, and requeue the stalled contacts.",
                "evidence_type": "resolved ticket",
                "base_score": 0.61,
                "metrics": crm_metrics,
            },
            {
                "reference": "TW-GENERIC-1",
                "title": "Create weekly dashboard rotation review task",
                "text": "Create a weekly dashboard service rotation review task and update the tracker.",
                "evidence_type": "similar ticket",
                "base_score": 0.88,
                "metrics": generic_metrics,
            },
        ],
    )

    selected = select_primary_cluster(clustered["clusters"])
    candidate_by_reference = {candidate["reference"]: candidate for candidate in clustered["candidates"]}

    assert selected is not None
    assert selected["cluster_id"] == "crm_integration"
    assert candidate_by_reference["TW-CRM-1"]["coherence_score"] > candidate_by_reference["TW-GENERIC-1"]["coherence_score"]
    assert candidate_by_reference["TW-GENERIC-1"]["features"]["generic_only_overlap"] is True
    assert candidate_by_reference["TW-GENERIC-1"]["coherence_score"] < 0.25


def test_grounded_issue_matches_keeps_application_evidence_and_drops_false_positive_mail_cluster() -> None:
    grounded = grounded_issue_matches(
        (
            "RAG retrieval returns wrong mail certificate tickets for VPN incidents\n"
            "The application retrieval pipeline is surfacing email incidents as false positives after embedding similarity drift."
        ),
        [
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
        top_k=4,
    )

    assert grounded["evidence_conflict_flag"] is True
    assert grounded["matches"] == []


def test_retrieval_consensus_downweights_split_family_evidence() -> None:
    query_context = _query_context(
        "RAG retrieval returns wrong mail certificate tickets for VPN incidents\n"
        "Investigate cross-domain grounding and embedding similarity drift in the application pipeline."
    )
    confidence, consensus, evidence_clusters, conflict = _retrieval_consensus(
        query_context,
        kb_articles=[
            {
                "id": "APP-1",
                "jira_key": "APP-1",
                "title": "Embedding retrieval mismatch after similarity drift",
                "excerpt": "RAG pipeline returns cross-domain matches after embedding similarity drift.",
                "similarity_score": 0.86,
                "context_score": 0.62,
                "lexical_overlap": 0.42,
                "title_overlap": 0.34,
                "strong_overlap": 0.36,
                "topic_overlap": 0.52,
                "topic_mismatch": False,
                "domain_mismatch": False,
            },
            {
                "id": "MAIL-1",
                "jira_key": "MAIL-1",
                "title": "Mail relay deferred after certificate renewal",
                "excerpt": "Relay queue stalls after certificate renewal.",
                "similarity_score": 0.84,
                "context_score": 0.24,
                "lexical_overlap": 0.16,
                "title_overlap": 0.14,
                "strong_overlap": 0.15,
                "topic_overlap": 0.0,
                "topic_mismatch": True,
                "domain_mismatch": True,
            },
        ],
        similar_tickets=[],
        solution_recommendations=[],
        related_problems=[],
        raw_confidence=0.86,
    )

    assert confidence < 0.86
    assert consensus < 0.86
    assert evidence_clusters["clusters"]
    assert conflict is False
