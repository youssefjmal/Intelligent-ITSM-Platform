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


def build_classification_prompt(
    *,
    title: str,
    description: str,
    knowledge_section: str,
    recommendations_mode: str = "llm_general",
) -> str:
    if recommendations_mode == "comments_strong":
        mode_hint = "Knowledge Section contient des correspondances Jira fortes."
    else:
        mode_hint = "Knowledge Section peut etre partielle; reste strict sur le grounding."

    return (
        "Tu es un assistant ITSM. Reponds avec JSON valide uniquement, sans texte hors JSON.\n"
        "Knowledge-first strict:\n"
        "- Si Knowledge Section a des matchs Jira, base d'abord priority/category/recommendations sur commentaires + champs Jira.\n"
        "- Si Knowledge Section est vide ou insuffisante, utilise la connaissance IT generale.\n"
        "- Si matchs Jira presents mais support insuffisant pour 2-4 actions concretes, retourne recommendations=[].\n"
        "- N'invente jamais de Jira key, incident, correctif, action historique.\n"
        f"- Contexte: {mode_hint}\n"
        "Schema JSON strict:\n"
        "{\n"
        '  "priority": "critical|high|medium|low",\n'
        '  "category": "infrastructure|network|security|application|service_request|hardware|email",\n'
        '  "recommendations": ["2-4 actions courtes"] | [],\n'
        '  "notes": "explication courte du grounding Jira ou insuffisance",\n'
        '  "sources": ["Jira keys presentes dans Knowledge Section"]\n'
        "}\n"
        "Regles sources:\n"
        "- Si Knowledge Section utilisee, remplir sources avec les Jira keys utilisees (depuis [KEY]).\n"
        "- Si Knowledge Section vide/insuffisante, sources=[].\n\n"
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
        "Knowledge-first strict policy:\n"
        "- If Knowledge Section has Jira matches, base classification/recommendations/solution primarily on those Jira matches.\n"
        "- If Knowledge Section is empty or insufficient, use general IT knowledge.\n"
        "- Never invent Jira keys, incidents, fixes, or historical actions.\n"
        "- If Knowledge Section has matches, every recommendation must be explicitly supported by Jira comments or Jira fields.\n"
        "- If Jira support is insufficient for 2-4 concrete actions, return recommendations=[].\n"
        "- If Knowledge Section is empty, set confidence=\"low\" and sources=[].\n"
        "- When Knowledge Section is used, sources must contain Jira keys referenced from [KEY] patterns.\n"
        "JSON schema:\n"
        "{\n"
        '  "reply": "string",\n'
        '  "confidence": "low" | "medium" | "high",\n'
        '  "sources": ["Jira keys like ABC-123"],\n'
        '  "classification": {\n'
        '    "priority": "critical|high|medium|low",\n'
        '    "category": "infrastructure|network|security|application|service_request|hardware|email"\n'
        "  },\n"
        '  "recommendations": ["2-4 short concrete actions"] | [],\n'
        '  "notes": "short grounding explanation (Jira used or insufficient)",\n'
        '  "action": "create_ticket" | "none",\n'
        '  "solution": "string | null",\n'
        '  "ticket": {\n'
        '    "title": "string",\n'
        '    "description": "string",\n'
        '    "priority": "critical|high|medium|low",\n'
        '    "category": "infrastructure|network|security|application|service_request|hardware|email",\n'
        '    "tags": ["string"],\n'
        '    "assignee": "one of available assignees or null"\n'
        "  } | null\n"
        "}\n\n"
        f"{knowledge_section}"
        "Rules:\n"
        "- If Jira matches are strong and consistent, confidence=high.\n"
        "- If Jira matches exist but are partial/unclear, confidence=medium.\n"
        "- If no Jira matches, confidence=low and sources=[].\n"
        "- solution must be one string or null. Do not merge recommendations into solution.\n"
        "- recommendations must be a JSON array of strings.\n"
        "- If the user asks to create/open a ticket, set action=create_ticket and fill ticket.\n"
        "- Otherwise action=none and ticket=null.\n"
        f"- Write reply, recommendations and notes in language: {lang}.\n"
        f"- Write ticket description in language: {lang}.\n"
        f"- Start the reply with this greeting: {greeting}.\n"
        f"- Available assignees: {assignee_list}.\n"
        f"- Stats: {stats}.\n"
        f"- Question: {question}\n"
    )
