"""AI helpers powered by Ollama with rule-based fallbacks."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import settings
from app.models.enums import TicketCategory, TicketPriority

logger = logging.getLogger(__name__)

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
        "patterns": [
            "mot de passe",
            "password",
            "login",
            "connexion",
            "sign in",
            "authent",
        ],
        "fr": (
            "Verifiez la saisie (majuscule/Clavier), tentez une reconnexion, "
            "puis utilisez la reinitialisation du mot de passe si besoin. "
            "Essayez aussi en navigation privee."
        ),
        "en": (
            "Check credentials (caps/keyboard), try logging in again, "
            "then use password reset if needed. "
            "Also try an incognito window."
        ),
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
        "fr": (
            "Faites un hard refresh (Ctrl+F5), videz cache/cookies, "
            "ou testez avec un autre navigateur."
        ),
        "en": (
            "Do a hard refresh (Ctrl+F5), clear cache/cookies, "
            "or try a different browser."
        ),
    },
    {
        "patterns": [
            "verification",
            "email de verification",
            "verification email",
            "verification mail",
            "code de verification",
        ],
        "fr": (
            "Verifiez le dossier spam, attendez quelques minutes, "
            "puis utilisez le bouton de renvoi si disponible."
        ),
        "en": (
            "Check your spam folder, wait a few minutes, "
            "then use the resend button if available."
        ),
    },
    {
        "patterns": [
            "acces refuse",
            "access denied",
            "permission",
            "autorisation",
            "role",
        ],
        "fr": (
            "Verifiez votre role/profil, puis deconnectez-vous et reconnectez-vous. "
            "Si le probleme persiste, demandez l'ajout des droits requis."
        ),
        "en": (
            "Verify your role/profile, then log out and back in. "
            "If it persists, request the required permissions."
        ),
    },
]


def _rule_based_classify(title: str, description: str) -> tuple[TicketPriority, TicketCategory, list[str]]:
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


def _normalize_locale(locale: str | None) -> str:
    return "en" if (locale or "").lower().startswith("en") else "fr"


def _ollama_generate(prompt: str) -> str:
    url = f"{settings.OLLAMA_BASE_URL}/api/generate"
    payload = {"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False}
    with httpx.Client(timeout=60) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return str(data.get("response", "")).strip()


def _extract_json(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return None


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


def _is_high_risk(text: str) -> bool:
    return _contains_any(text, HIGH_RISK_KEYWORDS)


def _suggest_quick_fix(question: str, *, lang: str) -> str | None:
    text = question.lower()
    if _is_high_risk(text):
        return None
    for fix in EASY_FIXES:
        if _contains_any(text, fix["patterns"]):
            return str(fix[lang])
    return None


def _explicit_ticket_request(question: str) -> bool:
    text = question.lower()
    return _contains_any(text, TICKET_REQUEST_KEYWORDS)


def _append_solution(reply: str, solution: str, *, lang: str) -> str:
    if not solution:
        return reply
    label = "Solution rapide" if lang == "fr" else "Quick fix"
    if reply:
        return f"{reply}\n\n{label}:\n- {solution}"
    return f"{label}:\n- {solution}"


def classify_ticket(title: str, description: str) -> tuple[TicketPriority, TicketCategory, list[str]]:
    prompt = (
        "Tu es un assistant ITSM. Analyse le ticket ci-dessous et reponds uniquement en JSON.\n"
        "Champs attendus:\n"
        "- priority: critical|high|medium|low\n"
        "- category: bug|feature|support|infrastructure|security\n"
        "- recommendations: tableau de 2-4 courtes recommandations en francais\n\n"
        f"Titre: {title}\n"
        f"Description: {description}\n"
    )
    try:
        reply = _ollama_generate(prompt)
        data = _extract_json(reply)
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


def build_chat_reply(
    question: str,
    stats: dict,
    top_tickets: list[str],
    *,
    locale: str | None = None,
    assignees: list[str] | None = None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    lang = _normalize_locale(locale)
    assignee_list = assignees or []
    wants_ticket = _explicit_ticket_request(question)
    prompt = (
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
        '    "category": "bug|feature|support|infrastructure|security",\n'
        '    "tags": ["string"],\n'
        '    "assignee": "one of available assignees or null"\n'
        "  }\n"
        "}\n\n"
        "Rules:\n"
        "- If the user asks to create/open a ticket, set action=create_ticket and fill ticket.\n"
        "- Otherwise action=none and ticket=null.\n"
        "- If the issue is simple and safe to solve without a ticket, include a short solution.\n"
        "- If you provide a solution for a simple issue, set action=none.\n"
        f"- Write the reply and ticket description in language: {lang}.\n"
        f"- Available assignees: {assignee_list}.\n"
        f"- Stats: {stats}.\n"
        f"- Top tickets: {top_tickets}.\n"
        f"- Question: {question}\n"
    )
    try:
        reply = _ollama_generate(prompt)
        data = _extract_json(reply)
        if data and "reply" in data:
            reply_text = str(data.get("reply", ""))
            action = data.get("action")
            solution = data.get("solution")
            quick_fix = _suggest_quick_fix(question, lang=lang)
            if quick_fix and action == "create_ticket" and not wants_ticket:
                action = "none"
                data["ticket"] = None
                reply_text = _append_solution(reply_text, quick_fix, lang=lang)
            if isinstance(solution, list):
                solution = " ".join(str(item) for item in solution if item)
            if isinstance(solution, str) and solution.strip() and action in {None, "none"}:
                reply_text = _append_solution(reply_text, solution.strip(), lang=lang)
            elif action in {None, "none"}:
                if quick_fix:
                    reply_text = _append_solution(reply_text, quick_fix, lang=lang)
            return reply_text, action, data.get("ticket")
        quick_fix = _suggest_quick_fix(question, lang=lang)
        if quick_fix:
            reply = _append_solution(str(reply), quick_fix, lang=lang)
        return reply, None, None
    except Exception as exc:
        logger.warning("Ollama chat failed: %s", exc)
        error_reply = "LLM is unavailable. Please try again." if lang == "en" else "LLM indisponible. Reessayez."
        quick_fix = _suggest_quick_fix(question, lang=lang)
        if quick_fix:
            error_reply = _append_solution(error_reply, quick_fix, lang=lang)
        return error_reply, None, None
