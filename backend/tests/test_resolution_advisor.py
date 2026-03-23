from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.enums import UserRole
from app.schemas.ai import ChatMessage, ChatRequest
from app.services.ai import orchestrator
from app.services.ai.resolution_advisor import build_resolution_advice


def test_resolution_advice_prefers_resolved_ticket_and_reuses_root_cause() -> None:
    retrieval = {
        "similar_tickets": [
            {
                "id": "TW-1001",
                "status": "resolved",
                "resolution_snippet": "Reset the Outlook profile and recreate the OST file, then verify mail flow is restored.",
                "similarity_score": 0.94,
            },
            {
                "id": "TW-1002",
                "status": "resolved",
                "resolution_snippet": "Recreate the OST cache after resetting the Outlook profile.",
                "similarity_score": 0.88,
            },
        ],
        "kb_articles": [
            {
                "id": "KB-77",
                "title": "Outlook recovery",
                "excerpt": "Use the standard Outlook mailbox recovery checklist.",
                "similarity_score": 0.7,
            }
        ],
        "solution_recommendations": [
            {
                "text": "Reset Outlook and rebuild the OST cache.",
                "source": "jira_comment",
                "source_id": "TEAMWILL-52",
                "quality_score": 0.92,
                "confidence": 0.84,
            }
        ],
        "related_problems": [
            {
                "id": "PB-01",
                "root_cause": "Corrupted Outlook OST cache after profile changes.",
                "match_reason": "Recurring Outlook pattern",
                "similarity_score": 0.75,
            }
        ],
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["tentative"] is False
    assert advice["recommended_action"].startswith("Reset the Outlook profile")
    assert "TW-1001" in advice["reasoning"]
    assert advice["probable_root_cause"] == "Corrupted Outlook OST cache after profile changes."
    assert advice["root_cause"] == advice["probable_root_cause"]
    assert advice["evidence_sources"][0]["evidence_type"] == "resolved ticket"
    assert advice["evidence_sources"][0]["reference"] == "TW-1001"
    assert advice["evidence_sources"][0]["relevance"] > 0
    assert advice["evidence_sources"][0]["why_relevant"]
    assert advice["why_this_matches"]
    assert advice["validation_steps"]
    assert advice["fallback_action"]
    assert advice["response_text"].startswith("Recommended action:")


def test_resolution_advice_prefers_fix_comment_over_generic_kb() -> None:
    retrieval = {
        "query_context": {
            "query": "VPN certificate import fails and users cannot reconnect",
            "title": "VPN certificate import fails and users cannot reconnect",
            "description": "Affected users need the VPN client certificate repaired before access can be restored.",
            "tokens": ["vpn", "certificate", "import", "fails", "users", "reconnect", "client", "access", "restored"],
            "title_tokens": ["vpn", "certificate", "import", "reconnect"],
            "focus_terms": ["vpn", "certificate", "import", "client"],
            "domains": ["network", "security"],
            "metadata": {"category": "network"},
        },
        "similar_tickets": [],
        "kb_articles": [
            {
                "id": "KB-20",
                "title": "VPN checklist",
                "excerpt": "Review the standard VPN troubleshooting checklist and investigate the issue.",
                "similarity_score": 0.79,
            }
        ],
        "solution_recommendations": [
            {
                "text": "Reimport the VPN client certificate and restart the VPN service to restore access.",
                "source": "jira_comment",
                "source_id": "TEAMWILL-61",
                "quality_score": 0.9,
                "confidence": 0.86,
            }
        ],
        "related_problems": [],
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["tentative"] is False
    assert advice["recommended_action"].startswith("Reimport the VPN client certificate")
    assert advice["evidence_sources"][0]["evidence_type"] == "comment"
    assert "TEAMWILL-61" in advice["reasoning"]
    assert advice["evidence_sources"][0]["why_relevant"]
    assert advice["why_this_matches"]


def test_resolution_advice_marks_tentative_when_only_problem_evidence_exists() -> None:
    retrieval = {
        "query_context": {
            "query": "SSO login fails after certificate rotation",
            "title": "SSO login fails after certificate rotation",
            "description": "Users cannot sign in because the identity provider certificate appears stale.",
            "tokens": ["sso", "login", "fails", "certificate", "rotation", "identity", "provider", "stale"],
            "title_tokens": ["sso", "login", "certificate", "rotation"],
            "focus_terms": ["sso", "login", "certificate"],
            "domains": ["security"],
            "metadata": {"category": "security"},
        },
        "similar_tickets": [],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [
            {
                "id": "PB-42",
                "root_cause": "Expired SSO signing certificate on the identity provider.",
                "match_reason": "Known auth recurrence",
                "similarity_score": 0.67,
            }
        ],
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["tentative"] is True
    assert advice["display_mode"] == "tentative_diagnostic"
    assert advice["recommended_action"].startswith("Verify the relevant authentication token, certificate, or policy state")
    assert advice["probable_root_cause"] == "Expired SSO signing certificate on the identity provider."
    assert advice["root_cause"] is None
    assert advice["confidence_band"] == "low"
    assert advice["next_best_actions"]


def test_resolution_advice_extracts_action_from_resolution_marker_text() -> None:
    retrieval = {
        "query_context": {
            "query": "Teams message forwarding stopped after connector rotation",
            "title": "Teams message forwarding stopped after connector rotation",
            "tokens": ["teams", "message", "forwarding", "stopped", "connector", "rotation"],
            "title_tokens": ["teams", "forwarding", "connector", "rotation"],
            "focus_terms": ["forwarding", "connector", "rotation"],
            "domains": ["email"],
            "metadata": {"category": "email"},
        },
        "similar_tickets": [
            {
                "id": "TW-MOCK-009",
                "status": "resolved",
                "resolution_snippet": "Resolved by rebuilt the forwarding rule with the current connector identity after connector rotation.",
                "similarity_score": 0.88,
                "context_score": 0.58,
                "lexical_overlap": 0.42,
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "source": "hybrid_jira_local",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["tentative"] is False
    assert advice["recommended_action"].startswith("Rebuild the forwarding rule")
    assert "resolved by" not in advice["recommended_action"].lower()
    assert advice["confidence"] >= 0.6
    assert advice["match_summary"] is not None
    assert "forwarding" in advice["match_summary"].lower()
    assert advice["next_best_actions"][0].startswith("Verify the affected relay")


def test_resolution_advice_applies_tentative_confidence_penalty() -> None:
    strong_retrieval = {
        "query_context": {
            "query": "VPN route bundle missing ERP subnet after policy update",
            "title": "VPN route bundle missing ERP subnet after policy update",
            "tokens": ["vpn", "route", "bundle", "missing", "erp", "subnet", "policy", "update"],
            "title_tokens": ["vpn", "route", "bundle", "erp", "subnet"],
            "focus_terms": ["vpn", "route", "bundle", "erp", "subnet"],
            "domains": ["network"],
            "metadata": {"category": "network"},
        },
        "similar_tickets": [
            {
                "id": "TW-4100",
                "status": "resolved",
                "resolution_snippet": "Restore the ERP routes to the VPN split-tunnel configuration and reconnect affected users.",
                "similarity_score": 0.86,
                "context_score": 0.62,
                "lexical_overlap": 0.46,
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "source": "jira_semantic",
    }
    tentative_retrieval = {
        "query_context": {
            "query": "Finance users cannot reach the ERP site after remote access changes",
            "title": "Finance users cannot reach the ERP site after remote access changes",
            "tokens": ["finance", "users", "cannot", "reach", "erp", "site", "remote", "access", "changes"],
            "title_tokens": ["finance", "erp", "site", "remote", "access"],
            "focus_terms": ["finance", "site", "access"],
            "domains": ["network"],
            "metadata": {"category": "network"},
        },
        "similar_tickets": [
            {
                "id": "TW-4100",
                "status": "resolved",
                "resolution_snippet": "Restore the ERP routes to the VPN split-tunnel configuration and reconnect affected users.",
                "similarity_score": 0.86,
                "context_score": 0.14,
                "lexical_overlap": 0.1,
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "source": "jira_semantic",
    }

    strong_advice = build_resolution_advice(strong_retrieval, lang="en")
    tentative_advice = build_resolution_advice(tentative_retrieval, lang="en")

    assert strong_advice is not None
    assert tentative_advice is not None
    assert strong_advice["tentative"] is False
    assert tentative_advice["tentative"] is True
    assert tentative_advice["display_mode"] == "tentative_diagnostic"
    assert tentative_advice["recommended_action"].startswith("Verify the VPN route, gateway, or policy path")
    assert tentative_advice["confidence"] < strong_advice["confidence"]
    assert 0.2 <= tentative_advice["confidence"] <= 0.5


def test_resolution_advice_multi_source_agreement_clears_tentative_and_boosts_confidence() -> None:
    retrieval = {
        "query_context": {
            "query": "Teams forwarding fails after connector rotation",
            "title": "Teams forwarding fails after connector rotation",
            "tokens": ["teams", "forwarding", "fails", "connector", "rotation"],
            "title_tokens": ["teams", "forwarding", "connector", "rotation"],
            "focus_terms": ["teams", "rotation"],
            "domains": ["email"],
            "metadata": {"category": "email"},
        },
        "similar_tickets": [
            {
                "id": "TW-5200",
                "status": "resolved",
                "resolution_snippet": "Resolved by rebuilt the forwarding rule with the current connector identity and restarted message sync.",
                "similarity_score": 0.81,
                "context_score": 0.14,
                "lexical_overlap": 0.1,
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [
            {
                "text": "Rebuild the forwarding rule with the current connector identity, then restart message sync.",
                "source_id": "TW-5200-comment",
                "quality_score": 0.78,
                "confidence": 0.76,
                "context_score": 0.15,
                "lexical_overlap": 0.12,
            }
        ],
        "related_problems": [],
        "source": "hybrid_jira_local",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["tentative"] is False
    assert advice["recommendation_mode"] == "resolved_ticket_grounded"
    assert advice["recommended_action"].startswith("Rebuild the forwarding rule")
    assert advice["confidence"] >= 0.6
    assert len(advice["evidence_sources"]) >= 2
    assert advice["confidence_band"] in {"medium", "high"}


def test_handle_chat_uses_grounded_resolution_reply_for_fix_queries(monkeypatch) -> None:
    retrieval = {
        "similar_tickets": [
            {
                "id": "TW-3001",
                "status": "resolved",
                "resolution_snippet": "Flush the DNS cache and restart the VPN adapter, then reconnect.",
                "similarity_score": 0.91,
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "confidence": 0.91,
        "source": "hybrid_jira_local",
    }

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: [])
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(orchestrator, "unified_retrieve", lambda *args, **kwargs: retrieval)
    monkeypatch.setattr(
        orchestrator,
        "ollama_generate",
        lambda *args, **kwargs: '{"opening":"Good morning","evidence_summary":"A resolved VPN DNS incident matches the same reconnect pattern.","caution_note":""}',
    )

    payload = ChatRequest(messages=[ChatMessage(role="user", content="How do I fix the VPN DNS issue?")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")

    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.reply.startswith("Summary:")
    assert "Recommended Action:" in response.reply
    assert "Why this matches:" in response.reply
    assert "Validation:" in response.reply
    assert response.suggestions.resolution_advice is not None
    assert response.suggestions.resolution_advice.recommended_action.startswith("Flush the DNS cache")


def test_resolution_advice_rejects_unrelated_hardware_fix_for_payroll_export_issue() -> None:
    retrieval = {
        "query_context": {
            "query": "Payroll export CSV writes broken date values",
            "title": "Payroll export CSV writes broken date values",
            "tokens": ["payroll", "export", "csv", "date", "values", "imported", "finance", "workbook"],
            "title_tokens": ["payroll", "export", "csv", "date", "values"],
            "focus_terms": ["payroll", "export", "csv", "date", "workbook"],
            "domains": ["application"],
            "metadata": {"category": "application"},
        },
        "similar_tickets": [
            {
                "id": "TW-88",
                "status": "resolved",
                "resolution_snippet": "Replace the keyboard and dock, then validate desk connectivity.",
                "similarity_score": 0.97,
                "context_score": 0.01,
                "domain_mismatch": True,
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [
            {
                "id": "PB-12",
                "root_cause": "Mail workers are not refreshing the relay trust store.",
                "match_reason": "Email relay recurrence",
                "similarity_score": 0.82,
                "context_score": 0.0,
                "domain_mismatch": True,
            }
        ],
        "source": "hybrid_jira_local",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["display_mode"] == "no_strong_match"
    assert advice["recommended_action"] is None
    assert advice["recommendation_mode"] == "fallback_diagnostic"
    assert advice["evidence_sources"] == []
    assert advice["match_summary"] == "Matched on payroll, export, csv, date."


def test_resolution_advice_filters_low_confidence_unrelated_distribution_rule_action() -> None:
    retrieval = {
        "query_context": {
            "query": "Add payroll distribution rule for approval notices",
            "title": "Add payroll distribution rule for approval notices",
            "description": "Managers should receive payroll approval notices through the expected email distribution rule.",
            "tokens": ["add", "payroll", "distribution", "rule", "approval", "notices", "managers", "email"],
            "title_tokens": ["payroll", "distribution", "rule", "approval", "notices"],
            "focus_terms": ["payroll", "distribution", "approval", "managers", "email"],
            "domains": ["email", "application"],
            "metadata": {"category": "email"},
        },
        "similar_tickets": [
            {
                "id": "TW-6010",
                "status": "resolved",
                "resolution_snippet": "Scheduled the webhook reminder task and confirmed the team subscription.",
                "similarity_score": 0.64,
                "context_score": 0.24,
                "lexical_overlap": 0.04,
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "source": "jira_semantic",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["display_mode"] == "tentative_diagnostic"
    assert advice["recommended_action"] == "Verify the payroll approval notification distribution rule and confirm the expected manager recipient mapping."
    assert "webhook" not in advice["recommended_action"].lower()


def test_resolution_advice_returns_tentative_diagnostic_for_aligned_weak_evidence() -> None:
    retrieval = {
        "query_context": {
            "query": "Add payroll distribution rule for approval notices",
            "title": "Add payroll distribution rule for approval notices",
            "description": "Managers should receive payroll approval notices through the expected email distribution rule.",
            "tokens": ["add", "payroll", "distribution", "rule", "approval", "notices", "managers", "email"],
            "title_tokens": ["payroll", "distribution", "rule", "approval", "notices"],
            "focus_terms": ["payroll", "distribution", "approval", "managers", "email"],
            "domains": ["email", "application"],
            "metadata": {"category": "email"},
        },
        "similar_tickets": [
            {
                "id": "TW-6011",
                "status": "resolved",
                "resolution_snippet": "Verify the payroll approval notification rule and confirm manager recipient mapping before rollout.",
                "similarity_score": 0.69,
                "context_score": 0.14,
                "lexical_overlap": 0.12,
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "source": "jira_semantic",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["display_mode"] == "tentative_diagnostic"
    assert advice["filtered_weak_match"] is False
    assert advice["recommended_action"] == "Verify the payroll approval notification distribution rule and confirm the expected manager recipient mapping."
    assert 0.22 <= advice["action_relevance_score"] <= 1.0


def test_resolution_advice_fallback_respects_selected_export_family_over_notification_tokens() -> None:
    retrieval = {
        "query_context": {
            "query": "Payroll export approval file writes invalid date columns",
            "title": "Payroll export approval file writes invalid date columns",
            "description": "The export is produced, but the date columns break the downstream import schema.",
            "tokens": ["payroll", "export", "approval", "date", "columns", "invalid", "mapping", "import"],
            "title_tokens": ["payroll", "export", "date", "columns", "mapping"],
            "focus_terms": ["export", "date", "mapping", "import"],
            "topics": ["payroll_export", "notification_distribution"],
            "domains": ["application"],
            "metadata": {"category": "application"},
        },
        "similar_tickets": [],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "source": "fallback_rules",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["display_mode"] == "no_strong_match"
    assert advice["fallback_action"] is not None
    assert "export" in advice["fallback_action"].lower()
    assert "notification" not in advice["fallback_action"].lower()
    assert "recipient" not in advice["fallback_action"].lower()


def test_resolution_advice_prefers_context_aligned_export_fix_over_unrelated_higher_similarity() -> None:
    retrieval = {
        "query_context": {
            "query": "Payroll export CSV writes broken date values",
            "title": "Payroll export CSV writes broken date values",
            "tokens": ["payroll", "export", "csv", "date", "values", "imported", "finance", "workbook"],
            "title_tokens": ["payroll", "export", "csv", "date", "values"],
            "focus_terms": ["payroll", "export", "csv", "date", "workbook"],
            "domains": ["application"],
            "metadata": {"category": "application"},
        },
        "similar_tickets": [
            {
                "id": "TW-77",
                "status": "resolved",
                "resolution_snippet": "Replace the keyboard and dock, then validate desk connectivity.",
                "similarity_score": 0.96,
                "context_score": 0.01,
                "domain_mismatch": True,
            },
            {
                "id": "TW-78",
                "status": "resolved",
                "resolution_snippet": "Correct the CSV date serializer, regenerate the export, and validate the import workbook.",
                "similarity_score": 0.78,
                "context_score": 0.64,
                "domain_mismatch": False,
            },
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "source": "jira_semantic",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["tentative"] is False
    assert advice["recommended_action"].startswith("Correct the CSV date serializer")
    assert advice["evidence_sources"][0]["reference"] == "TW-78"
    assert advice["next_best_actions"][1].startswith("Verify the probable root cause") or advice["next_best_actions"][1].startswith("Generate")


def test_resolution_advice_exposes_structured_match_and_evidence_metadata() -> None:
    retrieval = {
        "query_context": {
            "query": "Archive access denied after ACL change",
            "title": "Archive access denied after ACL change",
            "description": "Legal users cannot open protected archive folders after a permission change.",
            "tokens": ["archive", "access", "denied", "acl", "change", "legal", "folders", "permission"],
            "title_tokens": ["archive", "access", "denied", "acl", "change"],
            "focus_terms": ["archive", "access", "acl", "legal", "permission"],
            "domains": ["security"],
            "metadata": {"category": "security"},
        },
        "similar_tickets": [
            {
                "id": "TW-MOCK-027",
                "title": "Archive access denied after ACL mapping drift",
                "status": "resolved",
                "resolution_snippet": "Restore the archive ACL mapping for the legal security group and confirm read access.",
                "similarity_score": 0.89,
                "context_score": 0.68,
                "lexical_overlap": 0.42,
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [
            {
                "id": "PB-ACL-01",
                "title": "Archive ACL drift",
                "root_cause": "Archive ACL mapping drift after the latest permission change.",
                "match_reason": "Recurring archive permission pattern",
                "similarity_score": 0.74,
            }
        ],
        "source": "hybrid_jira_local",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["display_mode"] == "evidence_action"
    assert advice["confidence_band"] in {"medium", "high"}
    assert advice["root_cause"] == "Archive ACL mapping drift after the latest permission change."
    assert advice["supporting_context"] is None or isinstance(advice["supporting_context"], str)
    assert len(advice["why_this_matches"]) >= 2
    assert all(isinstance(item, str) and item for item in advice["why_this_matches"])
    assert advice["evidence_sources"]
    assert advice["evidence_sources"][0]["title"] == "Archive access denied after ACL mapping drift"
    assert advice["evidence_sources"][0]["why_relevant"]
    assert advice["validation_steps"]
    assert advice["fallback_action"]


def test_resolution_advice_builds_incident_cluster_and_impact_summary() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    retrieval = {
        "query_context": {
            "query": "VPN login fails for remote users after MFA policy change",
            "title": "VPN login fails for remote users after MFA policy change",
            "tokens": ["vpn", "login", "fails", "remote", "users", "mfa", "policy", "change"],
            "title_tokens": ["vpn", "login", "remote", "users", "mfa"],
            "focus_terms": ["vpn", "mfa", "login", "remote"],
            "domains": ["network", "security"],
            "metadata": {"category": "network"},
        },
        "similar_tickets": [
            {
                "id": "TW-801",
                "title": "VPN login loop after MFA policy update",
                "status": "open",
                "created_at": (now - dt.timedelta(hours=3)).isoformat(),
                "updated_at": (now - dt.timedelta(hours=2)).isoformat(),
                "resolution_snippet": "Refresh the VPN policy session and re-authenticate affected users.",
                "similarity_score": 0.82,
                "context_score": 0.56,
                "lexical_overlap": 0.34,
            },
            {
                "id": "TW-802",
                "title": "Remote user MFA loop on VPN login",
                "status": "in-progress",
                "created_at": (now - dt.timedelta(hours=4)).isoformat(),
                "updated_at": (now - dt.timedelta(minutes=90)).isoformat(),
                "resolution_snippet": "Refresh the VPN policy session and re-authenticate affected users.",
                "similarity_score": 0.8,
                "context_score": 0.52,
                "lexical_overlap": 0.31,
            },
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "source": "hybrid_jira_local",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["incident_cluster"] is not None
    assert advice["incident_cluster"]["count"] == 2
    assert "similar tickets" in advice["incident_cluster"]["summary"].lower()
    assert advice["impact_summary"] is not None
    assert "vpn" in advice["impact_summary"].lower() or "remote" in advice["impact_summary"].lower()


def test_resolution_advice_filters_mail_transport_fix_for_crm_sync_ticket() -> None:
    retrieval = {
        "query_context": {
            "query": "CRM sync job stalls after token rotation",
            "title": "CRM sync job stalls after token rotation",
            "description": "The scheduled CRM sync starts on time, but it stalls after token rotation and never writes the latest contact updates.",
            "tokens": ["crm", "sync", "job", "stalls", "token", "rotation", "contact", "updates", "worker", "integration"],
            "title_tokens": ["crm", "sync", "job", "stalls", "token", "rotation"],
            "focus_terms": ["crm", "sync", "token", "rotation", "worker", "integration"],
            "domains": ["infrastructure", "security"],
            "metadata": {"category": "infrastructure"},
        },
        "similar_tickets": [],
        "kb_articles": [
            {
                "id": "KB-RELAY-9",
                "title": "Mail relay delivery deferred after certificate renewal",
                "excerpt": "Resolved by updating the relay certificate chain and clearing the deferred transport queue.",
                "similarity_score": 0.79,
                "context_score": 0.27,
                "lexical_overlap": 0.12,
                "title_overlap": 0.11,
                "domain_mismatch": False,
            }
        ],
        "solution_recommendations": [],
        "related_problems": [],
        "source": "jira_semantic",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["display_mode"] == "no_strong_match"
    assert advice["filtered_weak_match"] is False
    assert advice["recommended_action"] is None
    assert advice["action_relevance_score"] == 0.0


def test_resolution_advice_prefers_crm_worker_fix_over_unrelated_mail_candidate() -> None:
    retrieval = {
        "query_context": {
            "query": "CRM sync job stalls after token rotation",
            "title": "CRM sync job stalls after token rotation",
            "description": "The scheduled CRM sync starts on time, but it stalls after token rotation and never writes the latest contact updates.",
            "tokens": ["crm", "sync", "job", "stalls", "token", "rotation", "contact", "updates", "worker", "integration"],
            "title_tokens": ["crm", "sync", "job", "stalls", "token", "rotation"],
            "focus_terms": ["crm", "sync", "token", "rotation", "worker", "integration"],
            "domains": ["infrastructure", "security"],
            "metadata": {"category": "infrastructure"},
        },
        "similar_tickets": [
            {
                "id": "TW-CRM-1",
                "status": "resolved",
                "resolution_snippet": "Rotate the sync worker secret, restart the CRM sync worker, and requeue the stalled jobs.",
                "similarity_score": 0.72,
                "context_score": 0.62,
                "lexical_overlap": 0.34,
                "title_overlap": 0.31,
            },
            {
                "id": "TW-MAIL-1",
                "status": "resolved",
                "resolution_snippet": "Update the relay certificate chain and clear the deferred transport queue.",
                "similarity_score": 0.84,
                "context_score": 0.29,
                "lexical_overlap": 0.12,
                "title_overlap": 0.11,
                "domain_mismatch": False,
            },
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "source": "hybrid_jira_local",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["display_mode"] == "evidence_action"
    assert advice["tentative"] is False
    assert advice["recommended_action"].startswith("Rotate the sync worker secret")
    assert advice["evidence_sources"][0]["reference"] == "TW-CRM-1"
    assert advice["action_relevance_score"] >= 0.22


def test_resolution_advice_builds_specific_token_rotation_plan() -> None:
    retrieval = {
        "query_context": {
            "query": "CRM sync job stalls after token rotation",
            "title": "CRM sync job stalls after token rotation",
            "description": "The scheduled CRM sync starts on time, but it stalls after token rotation and never writes the latest contact updates.",
            "tokens": ["crm", "sync", "job", "stalls", "token", "rotation", "contact", "updates", "worker", "integration"],
            "title_tokens": ["crm", "sync", "job", "stalls", "token", "rotation"],
            "focus_terms": ["crm", "sync", "token", "rotation", "worker", "integration"],
            "strong_terms": ["crm", "sync", "token", "worker", "integration"],
            "domains": ["infrastructure", "security"],
            "topics": ["crm_integration"],
            "metadata": {"category": "infrastructure"},
        },
        "similar_tickets": [
            {
                "id": "TW-CRM-9",
                "status": "resolved",
                "resolution_snippet": "Rotate the sync worker secret, restart the CRM sync worker, and requeue the stalled jobs.",
                "similarity_score": 0.8,
                "context_score": 0.64,
                "lexical_overlap": 0.35,
                "title_overlap": 0.31,
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [
            {
                "text": "Worker kept using the previous token until the credential cache was reloaded.",
                "source_id": "TEAMWILL-CRM-9",
                "quality_score": 0.81,
                "confidence": 0.78,
                "context_score": 0.56,
                "lexical_overlap": 0.24,
                "strong_overlap": 0.26,
            }
        ],
        "related_problems": [],
        "source": "hybrid_jira_local",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    combined = " ".join(
        [
            advice["recommended_action"] or "",
            " ".join(advice["next_best_actions"]),
            " ".join(advice["validation_steps"]),
        ]
    ).lower()
    assert advice["display_mode"] == "evidence_action"
    assert "token" in combined or "credential" in combined
    assert "worker" in combined
    assert "crm sync" in combined or "crm" in combined
    assert "controlled crm sync" in combined or "affected record" in combined or "contact update" in combined
    assert "export" not in combined
    assert "dashboard" not in combined


def test_resolution_advice_rewrites_generic_check_logs_into_specific_ticket_action() -> None:
    retrieval = {
        "query_context": {
            "query": "CRM sync job stalls after token rotation",
            "title": "CRM sync job stalls after token rotation",
            "description": "The scheduled CRM sync starts on time, but it stalls after token rotation and never writes the latest contact updates.",
            "tokens": ["crm", "sync", "job", "stalls", "token", "rotation", "contact", "updates", "worker", "integration"],
            "title_tokens": ["crm", "sync", "job", "stalls", "token", "rotation"],
            "focus_terms": ["crm", "sync", "token", "rotation", "worker", "integration"],
            "strong_terms": ["crm", "sync", "token", "worker", "integration"],
            "domains": ["infrastructure", "security"],
            "topics": ["crm_integration"],
            "metadata": {"category": "infrastructure"},
        },
        "similar_tickets": [
            {
                "id": "TW-CRM-10",
                "status": "resolved",
                "resolution_snippet": "Check logs and restart service.",
                "similarity_score": 0.75,
                "context_score": 0.58,
                "lexical_overlap": 0.21,
                "title_overlap": 0.19,
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "source": "hybrid_jira_local",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["recommended_action"] is not None
    assert advice["recommended_action"].lower() != "check logs and restart service"
    assert "check logs" not in advice["recommended_action"].lower()
    assert "token" in advice["recommended_action"].lower() or "crm" in advice["recommended_action"].lower()
    assert any("worker" in step.lower() or "authentication" in step.lower() for step in advice["next_best_actions"] + advice["validation_steps"])


def test_resolution_advice_returns_insufficient_evidence_for_generic_low_signal_match() -> None:
    retrieval = {
        "query_context": {
            "query": "Weekly service issue review request after update",
            "title": "Weekly service issue review request after update",
            "description": "Need a review of a weekly request after an update.",
            "tokens": ["weekly", "service", "issue", "review", "request", "update"],
            "title_tokens": ["weekly", "service", "issue", "review", "request", "update"],
            "focus_terms": ["weekly", "review", "request", "update"],
            "domains": [],
            "metadata": {"category": "service_request"},
        },
        "similar_tickets": [
            {
                "id": "TW-GENERIC-1",
                "status": "resolved",
                "resolution_snippet": "Check logs and restart service.",
                "similarity_score": 0.56,
                "context_score": 0.16,
                "lexical_overlap": 0.12,
                "title_overlap": 0.11,
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "source": "local_lexical",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["recommendation_mode"] == "insufficient_evidence"
    assert advice["recommended_action"] is None


def test_resolution_advice_returns_insufficient_evidence_for_conflicting_clusters() -> None:
    retrieval = {
        "query_context": {
            "query": "CRM sync job stalls after token rotation",
            "title": "CRM sync job stalls after token rotation",
            "description": "The scheduled CRM sync starts on time, but it stalls after token rotation and never writes the latest contact updates.",
            "tokens": ["crm", "sync", "job", "stalls", "token", "rotation", "contact", "updates", "worker", "integration"],
            "title_tokens": ["crm", "sync", "job", "stalls", "token", "rotation"],
            "focus_terms": ["crm", "sync", "token", "rotation", "worker", "integration"],
            "domains": ["infrastructure", "security"],
            "metadata": {"category": "infrastructure"},
        },
        "similar_tickets": [
            {
                "id": "TW-CRM-2",
                "title": "CRM worker stalled after expired token cache",
                "status": "resolved",
                "resolution_snippet": "Reload the CRM worker token cache, restart the sync worker, and requeue the stalled contacts.",
                "similarity_score": 0.78,
                "context_score": 0.52,
                "lexical_overlap": 0.28,
                "title_overlap": 0.26,
                "strong_overlap": 0.28,
                "cluster_id": "crm_integration",
                "coherence_score": 0.66,
            },
            {
                "id": "TW-EXPORT-2",
                "title": "Payroll export fails after formatter update",
                "status": "resolved",
                "resolution_snippet": "Correct the CSV date serializer, regenerate the export, and validate the finance workbook import.",
                "similarity_score": 0.8,
                "context_score": 0.5,
                "lexical_overlap": 0.24,
                "title_overlap": 0.22,
                "strong_overlap": 0.26,
                "cluster_id": "payroll_export",
                "coherence_score": 0.63,
            },
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "source": "hybrid_jira_local",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["display_mode"] == "no_strong_match"
    assert advice["recommendation_mode"] == "insufficient_evidence"
    assert advice["recommended_action"] is None
    assert advice["fallback_action"] is None
    assert advice["next_best_actions"]
    assert any("Conflicting evidence" in item for item in advice["missing_information"])


def test_resolution_advice_composes_only_from_selected_cluster_evidence() -> None:
    retrieval = {
        "query_context": {
            "query": "CRM sync job stalls after token rotation",
            "title": "CRM sync job stalls after token rotation",
            "description": "The scheduled CRM sync starts on time, but it stalls after token rotation and never writes the latest contact updates.",
            "tokens": ["crm", "sync", "job", "stalls", "token", "rotation", "contact", "updates", "worker", "integration"],
            "title_tokens": ["crm", "sync", "job", "stalls", "token", "rotation"],
            "focus_terms": ["crm", "sync", "token", "rotation", "worker", "integration"],
            "domains": ["infrastructure", "security"],
            "metadata": {"category": "infrastructure"},
        },
        "similar_tickets": [
            {
                "id": "TW-CRM-3",
                "title": "CRM worker stalled after expired token cache",
                "status": "resolved",
                "resolution_snippet": "Reload the CRM worker token cache, restart the sync worker, and requeue the stalled contacts.",
                "similarity_score": 0.79,
                "context_score": 0.61,
                "lexical_overlap": 0.32,
                "title_overlap": 0.3,
                "strong_overlap": 0.3,
                "cluster_id": "crm_integration",
                "coherence_score": 0.76,
            },
            {
                "id": "TW-EXPORT-3",
                "title": "Payroll export fails after formatter update",
                "status": "resolved",
                "resolution_snippet": "Correct the CSV date serializer, regenerate the export, and validate the finance workbook import.",
                "similarity_score": 0.86,
                "context_score": 0.34,
                "lexical_overlap": 0.16,
                "title_overlap": 0.14,
                "strong_overlap": 0.14,
                "cluster_id": "payroll_export",
                "coherence_score": 0.41,
            },
        ],
        "kb_articles": [],
        "solution_recommendations": [
            {
                "text": "Reload the CRM worker token cache, restart the sync worker, and confirm contact updates resume.",
                "source_id": "TEAMWILL-CRM-3",
                "quality_score": 0.82,
                "confidence": 0.8,
                "context_score": 0.58,
                "lexical_overlap": 0.28,
                "strong_overlap": 0.28,
                "cluster_id": "crm_integration",
                "coherence_score": 0.74,
            },
            {
                "text": "Correct the CSV date serializer and validate the workbook import.",
                "source_id": "TEAMWILL-EXPORT-3",
                "quality_score": 0.84,
                "confidence": 0.79,
                "context_score": 0.33,
                "lexical_overlap": 0.15,
                "strong_overlap": 0.14,
                "cluster_id": "payroll_export",
                "coherence_score": 0.39,
            },
        ],
        "related_problems": [],
        "source": "hybrid_jira_local",
    }

    advice = build_resolution_advice(retrieval, lang="en")
    assert advice is not None
    combined_text = " ".join(
        [
            advice["recommended_action"] or "",
            advice["reasoning"],
            " ".join(advice["why_this_matches"]),
            " ".join(advice["validation_steps"]),
            " ".join(advice["next_best_actions"]),
        ]
    ).lower()
    assert advice["display_mode"] == "evidence_action"
    assert advice["recommended_action"].startswith("Reload the CRM worker token cache")
    assert {row["reference"] for row in advice["evidence_sources"]}.issubset({"TW-CRM-3", "TEAMWILL-CRM-3"})
    assert "csv" not in combined_text
    assert "export" not in combined_text
    assert "workbook" not in combined_text


def test_resolution_advice_root_cause_stays_inside_selected_cluster() -> None:
    retrieval = {
        "query_context": {
            "query": "CRM sync job stalls after token rotation",
            "title": "CRM sync job stalls after token rotation",
            "description": "The scheduled CRM sync starts on time, but it stalls after token rotation and never writes the latest contact updates.",
            "tokens": ["crm", "sync", "job", "stalls", "token", "rotation", "contact", "updates", "worker", "integration"],
            "title_tokens": ["crm", "sync", "job", "stalls", "token", "rotation"],
            "focus_terms": ["crm", "sync", "token", "rotation", "worker", "integration"],
            "domains": ["infrastructure", "security"],
            "metadata": {"category": "infrastructure"},
        },
        "similar_tickets": [
            {
                "id": "TW-CRM-3",
                "title": "CRM worker stalled after expired token cache",
                "status": "resolved",
                "resolution_snippet": "Reload the CRM worker token cache, restart the sync worker, and requeue the stalled contacts.",
                "similarity_score": 0.79,
                "context_score": 0.61,
                "lexical_overlap": 0.32,
                "title_overlap": 0.3,
                "strong_overlap": 0.3,
                "cluster_id": "crm_integration",
                "coherence_score": 0.76,
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [
            {
                "text": "Reload the CRM worker token cache, restart the sync worker, and confirm contact updates resume.",
                "source": "jira_comment",
                "source_id": "TEAMWILL-CRM-3",
                "quality_score": 0.82,
                "confidence": 0.8,
                "context_score": 0.58,
                "lexical_overlap": 0.29,
                "strong_overlap": 0.28,
                "cluster_id": "crm_integration",
                "coherence_score": 0.74,
            }
        ],
        "related_problems": [
            {
                "id": "PB-VPN-01",
                "title": "VPN sessions time out after policy cleanup",
                "root_cause": "A recent VPN policy cleanup left the MFA session timeout and split-tunnel routes out of sync for several user groups.",
                "match_reason": "Direct semantic/lexical match from problem knowledge",
                "similarity_score": 0.93,
                "context_score": 0.34,
                "lexical_overlap": 0.18,
                "title_overlap": 0.16,
                "strong_overlap": 0.1,
                "topic_overlap": 0.0,
                "cluster_id": "network_access",
                "coherence_score": 0.36,
                "topic_mismatch": True,
                "domain_mismatch": True,
            },
            {
                "id": "PB-CRM-01",
                "title": "CRM worker credential cache not refreshed",
                "root_cause": "The sync worker kept using the old integration credential after token rotation.",
                "match_reason": "Matches the CRM token-rotation incident family.",
                "similarity_score": 0.71,
                "context_score": 0.57,
                "lexical_overlap": 0.27,
                "title_overlap": 0.24,
                "strong_overlap": 0.24,
                "topic_overlap": 0.5,
                "cluster_id": "crm_integration",
                "coherence_score": 0.73,
            },
        ],
        "source": "hybrid_jira_local",
    }

    advice = build_resolution_advice(retrieval, lang="en")

    assert advice is not None
    assert advice["display_mode"] == "evidence_action"
    assert advice["root_cause"] == "The sync worker kept using the old integration credential after token rotation."
    assert {row["reference"] for row in advice["evidence_sources"]}.issubset({"TW-CRM-3", "TEAMWILL-CRM-3", "PB-CRM-01"})
    combined_text = " ".join(
        [
            advice["root_cause"] or "",
            advice["reasoning"],
            " ".join(advice["why_this_matches"]),
            " ".join(step["excerpt"] for step in advice["evidence_sources"]),
        ]
    ).lower()
    assert "vpn" not in combined_text
    assert "mfa" not in combined_text
    assert "split-tunnel" not in combined_text
