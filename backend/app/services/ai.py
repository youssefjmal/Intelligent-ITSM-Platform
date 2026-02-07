"""Rule-based AI helpers used until Ollama integration is added."""

from __future__ import annotations

from app.models.enums import TicketCategory, TicketPriority


def classify_ticket(title: str, description: str) -> tuple[TicketPriority, TicketCategory, list[str]]:
    text = f"{title} {description}".lower()

    if any(k in text for k in ["xss", "vulnerabil", "secur", "auth", "sso"]):
        priority = TicketPriority.critical
        category = TicketCategory.security
    elif any(k in text for k in ["smtp", "email", "notification"]):
        priority = TicketPriority.high
        category = TicketCategory.bug
    elif any(k in text for k in ["performance", "lent", "optimisation", "cache"]):
        priority = TicketPriority.high
        category = TicketCategory.infrastructure
    elif any(k in text for k in ["migration", "postgres", "database"]):
        priority = TicketPriority.high
        category = TicketCategory.infrastructure
    elif any(k in text for k in ["report", "dashboard", "export", "pdf", "excel"]):
        priority = TicketPriority.medium
        category = TicketCategory.feature
    else:
        priority = TicketPriority.medium
        category = TicketCategory.support

    recommendations = [
        "Verifier l'impact utilisateur et prioriser selon l'urgence.",
        "Collecter les logs et erreurs associes avant intervention.",
        "Documenter la resolution pour capitalisation.",
    ]
    return priority, category, recommendations


def build_chat_reply(question: str, stats: dict, top_tickets: list[str]) -> str:
    summary = (
        "Synthese rapide:\n"
        f"- Total: {stats['total']} | Ouverts: {stats['open']} | En cours: {stats['in_progress']}\n"
        f"- En attente: {stats['pending']} | Resolus: {stats['resolved']} | Fermes: {stats['closed']}\n"
        f"- Critiques: {stats['critical']} | Taux de resolution: {stats['resolution_rate']}%\n"
    )
    if top_tickets:
        tickets_list = "\n".join(f"- {t}" for t in top_tickets)
        return f"{summary}\nTickets prioritaires:\n{tickets_list}"
    return summary
