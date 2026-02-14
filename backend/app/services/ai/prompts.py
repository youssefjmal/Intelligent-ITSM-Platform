"""Prompt builders and constants for AI workflows."""

from __future__ import annotations

HIGH_RISK_KEYWORDS = [
    "outage",
    "panne",
    "indisponible",
    "incident",
    "critical",
    "critique",
    "secur",
    "vulnerab",
    "breach",
    "data leak",
    "perte de donnees",
    "production",
    "p0",
    "p1",
]

TICKET_REQUEST_KEYWORDS = [
    "create a ticket",
    "open a ticket",
    "raise a ticket",
    "log a ticket",
    "submit a ticket",
    "new ticket",
    "open an incident",
    "ouvrir un ticket",
    "cree un ticket",
    "creer un ticket",
    "ouvrir un incident",
    "declarer un incident",
    "signaler un incident",
]

EASY_FIXES = [
    {
        "patterns": ["mot de passe", "password", "login", "connexion", "sign in", "authent"],
        "fr": "Verifiez la saisie (majuscule/Clavier), tentez une reconnexion, puis utilisez la reinitialisation du mot de passe si besoin. Essayez aussi en navigation privee.",
        "en": "Check credentials (caps/keyboard), try logging in again, then use password reset if needed. Also try an incognito window.",
    },
    {
        "patterns": [
            "cache",
            "cookies",
            "navigateur",
            "browser",
            "chrome",
            "safari",
            "edge",
            "page blanche",
            "not loading",
            "ne s'affiche",
            "ui",
            "interface",
        ],
        "fr": "Faites un hard refresh (Ctrl+F5), videz cache/cookies, ou testez avec un autre navigateur.",
        "en": "Do a hard refresh (Ctrl+F5), clear cache/cookies, or try a different browser.",
    },
    {
        "patterns": ["verification", "email de verification", "verification email", "verification mail", "code de verification"],
        "fr": "Verifiez le dossier spam, attendez quelques minutes, puis utilisez le bouton de renvoi si disponible.",
        "en": "Check your spam folder, wait a few minutes, then use the resend button if available.",
    },
    {
        "patterns": ["acces refuse", "access denied", "permission", "autorisation", "role"],
        "fr": "Verifiez votre role/profil, puis deconnectez-vous et reconnectez-vous. Si le probleme persiste, demandez l'ajout des droits requis.",
        "en": "Verify your role/profile, then log out and back in. If it persists, request the required permissions.",
    },
]


def build_classification_prompt(*, title: str, description: str, knowledge_section: str) -> str:
    return (
        "Tu es un assistant ITSM. Analyse le ticket ci-dessous et reponds uniquement en JSON.\n"
        "Appuie-toi d'abord sur la connaissance issue des commentaires Jira historiques quand elle est pertinente.\n"
        "Champs attendus:\n"
        "- priority: critical|high|medium|low\n"
        "- category: infrastructure|network|security|application|service_request|hardware|email\n"
        "- recommendations: tableau de 2-4 courtes recommandations en francais\n\n"
        f"{knowledge_section}"
        f"Titre: {title}\n"
        f"Description: {description}\n"
    )


def build_chat_prompt(
    *,
    question: str,
    knowledge_section: str,
    lang: str,
    greeting: str,
    assignee_list: list[str],
    stats: dict,
    top_tickets: list[str],
) -> str:
    return (
        "You are an ITSM assistant. Return ONLY valid JSON.\n"
        "Schema:\n"
        "{\n"
        '  "reply": "string",\n'
        '  "action": "create_ticket" | "none",\n'
        '  "solution": "string | null",\n'
        '  "ticket": {\n'
        '    "title": "string",\n'
        '    "description": "string",\n'
        '    "priority": "critical|high|medium|low",\n'
        '    "category": "infrastructure|network|security|application|service_request|hardware|email",\n'
        '    "tags": ["string"],\n'
        '    "assignee": "one of available assignees or null"\n'
        "  }\n"
        "}\n\n"
        f"{knowledge_section}"
        "Rules:\n"
        "- Use JSM historical comments knowledge when relevant.\n"
        "- If the user asks to create/open a ticket, set action=create_ticket and fill ticket.\n"
        "- Otherwise action=none and ticket=null.\n"
        "- If the issue is simple and safe to solve without a ticket, include a short solution.\n"
        "- If you provide a solution for a simple issue, set action=none.\n"
        f"- Write the reply and ticket description in language: {lang}.\n"
        f"- Start the reply with this greeting: {greeting}.\n"
        f"- Available assignees: {assignee_list}.\n"
        f"- Stats: {stats}.\n"
        f"- Top tickets: {top_tickets}.\n"
        f"- Question: {question}\n"
    )
