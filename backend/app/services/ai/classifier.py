"""Ticket classification service with LLM + rule fallback."""

from __future__ import annotations

import logging

from app.models.enums import TicketCategory, TicketPriority
from app.services.ai.llm import extract_json, ollama_generate
from app.services.ai.prompts import build_classification_prompt
from app.services.jira_kb import build_jira_knowledge_block

logger = logging.getLogger(__name__)


def _rule_based_classify(title: str, description: str) -> tuple[TicketPriority, TicketCategory, list[str]]:
    text = f"{title} {description}".lower()
    if any(k in text for k in ["xss", "vulnerabil", "secur", "auth", "sso"]):
        priority = TicketPriority.critical
        category = TicketCategory.security
    elif any(k in text for k in ["smtp", "email", "outlook", "gmail", "mailbox", "distribution list"]):
        priority = TicketPriority.high
        category = TicketCategory.email
    elif any(k in text for k in ["performance", "lent", "optimisation", "cache"]):
        priority = TicketPriority.high
        category = TicketCategory.infrastructure
    elif any(k in text for k in ["migration", "postgres", "database", "server", "cloud", "aws", "azure", "vm", "virtualisation", "virtualization"]):
        priority = TicketPriority.high
        category = TicketCategory.infrastructure
    elif any(
        k in text
        for k in [
            "network",
            "reseau",
            "wifi",
            "wi-fi",
            "vpn",
            "dns",
            "dhcp",
            "ip address",
            "adresse ip",
            "latency",
            "latence",
            "packet loss",
            "perte de paquets",
            "router",
            "switch",
            "firewall",
            "proxy",
        ]
    ):
        priority = TicketPriority.high
        category = TicketCategory.network
    elif any(k in text for k in ["laptop", "ordinateur", "printer", "imprim", "keyboard", "mouse", "peripheral", "ecran", "monitor"]):
        priority = TicketPriority.medium
        category = TicketCategory.hardware
    elif any(k in text for k in ["access", "permission", "onboard", "account", "install", "demande", "request", "support", "helpdesk"]):
        priority = TicketPriority.medium
        category = TicketCategory.service_request
    elif any(k in text for k in ["report", "dashboard", "export", "pdf", "excel", "bug", "feature", "error", "crash", "api", "frontend", "backend"]):
        priority = TicketPriority.medium
        category = TicketCategory.application
    else:
        priority = TicketPriority.medium
        category = TicketCategory.service_request

    recommendations = [
        "Verifier l'impact utilisateur et prioriser selon l'urgence.",
        "Collecter les logs et erreurs associes avant intervention.",
        "Documenter la resolution pour capitalisation.",
    ]
    return priority, category, recommendations


def classify_ticket(title: str, description: str) -> tuple[TicketPriority, TicketCategory, list[str]]:
    description = description or title
    knowledge_block = build_jira_knowledge_block(f"{title}\n{description}", lang="fr")
    knowledge_section = f"{knowledge_block}\n\n" if knowledge_block else ""
    prompt = build_classification_prompt(title=title, description=description, knowledge_section=knowledge_section)
    try:
        reply = ollama_generate(prompt, json_mode=True)
        data = extract_json(reply)
        if not data:
            raise ValueError("invalid_json")
        priority = TicketPriority(data["priority"])
        category = TicketCategory(data["category"])
        recommendations = list(data.get("recommendations", []))
        if not recommendations:
            raise ValueError("missing_recommendations")
        return priority, category, recommendations
    except Exception as exc:
        logger.warning("Ollama classify failed, using fallback: %s", exc)
        return _rule_based_classify(title, description)
