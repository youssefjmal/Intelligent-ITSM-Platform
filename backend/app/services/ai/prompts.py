"""Prompt builders and constants for AI workflows."""

from __future__ import annotations

import json

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
        "Analyse d'abord le ticket avant de recommander:\n"
        "- Extrais les signaux techniques cles: erreurs, metriques, changements de configuration, symptomes.\n"
        "- Base chaque recommandation uniquement sur ces signaux.\n"
        "- Evite les conseils generiques.\n"
        "Knowledge-first strict:\n"
        "- Si Knowledge Section a des matchs Jira, base d'abord priority/ticket_type/category/recommendations sur commentaires + champs Jira.\n"
        "- Si Knowledge Section est vide ou insuffisante, utilise la connaissance IT generale.\n"
        "- Si matchs Jira presents mais support insuffisant pour 2-4 actions concretes, retourne recommendations=[].\n"
        "- N'invente jamais de Jira key, incident, correctif, action historique.\n"
        f"- Contexte: {mode_hint}\n"
        "Schema JSON strict:\n"
        "{\n"
        '  "priority": "critical|high|medium|low",\n'
        '  "ticket_type": "incident|service_request",\n'
        '  "category": "infrastructure|network|security|application|service_request|hardware|email",\n'
        '  "technical_signals": ["3-8 signaux techniques issus du ticket et/ou Jira"],\n'
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
        "Before answering, analyze the ticket context:\n"
        "- Extract key technical signals (errors, metrics, config changes, symptoms).\n"
        "- Base recommendations strictly on those signals.\n"
        "- Avoid generic advice.\n"
        "Knowledge-first strict policy:\n"
        "- If Knowledge Section has Jira matches, base classification/recommendations/solution primarily on those Jira matches.\n"
        "- If Knowledge Section is empty or insufficient, use general IT knowledge.\n"
        "- Never invent Jira keys, incidents, fixes, or historical actions.\n"
        "- If Knowledge Section has matches, every recommendation must be explicitly supported by Jira comments or Jira fields.\n"
        "- If Jira support is insufficient for 2-4 concrete actions, return recommendations=[].\n"
        "- If Knowledge Section is empty, set confidence=\"low\" and sources=[].\n"
        "- When Knowledge Section is used, sources must contain Jira keys referenced from [KEY] patterns.\n"
        "- If a specific ticket ID is present in the user request, anchor the answer to that single ticket and do not switch to a multi-ticket summary.\n"
        "- If the question contains a compact conversation context block, treat it as authoritative session memory and keep follow-up answers tied to that context.\n"
        "- Distinguish retrieved facts from inference. Do not present inference as confirmed fact.\n"
        "- If evidence is weak, say so explicitly and prefer concrete next checks over generic filler.\n"
        "JSON schema:\n"
        "{\n"
        '  "reply": "string",\n'
        '  "confidence": "low" | "medium" | "high",\n'
        '  "sources": ["Jira keys like ABC-123"],\n'
        '  "classification": {\n'
        '    "priority": "critical|high|medium|low",\n'
        '    "ticket_type": "incident|service_request",\n'
        '    "category": "infrastructure|network|security|application|service_request|hardware|email"\n'
        "  },\n"
        '  "technical_signals": ["3-8 short technical signals"],\n'
        '  "recommendations": ["2-4 short concrete actions"] | [],\n'
        '  "notes": "short grounding explanation (Jira used or insufficient)",\n'
        '  "action": "create_ticket" | "none",\n'
        '  "solution": "string | null",\n'
        '  "ticket": {\n'
        '    "title": "string",\n'
        '    "description": "string",\n'
        '    "priority": "critical|high|medium|low",\n'
        '    "ticket_type": "incident|service_request",\n'
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


def build_chat_grounded_prompt(
    *,
    question: str,
    grounding: dict,
    lang: str,
    greeting: str,
) -> str:
    return (
        "You are an ITSM assistant formatting a resolver-approved answer.\n"
        "Return ONLY valid JSON.\n"
        "The resolver has already decided the recommendation content.\n"
        "You must preserve the resolver's truth exactly.\n"
        "The final answer will be rendered into fixed sections by the application.\n"
        "Your job is only to provide short supporting phrasing for those sections.\n"
        "Do NOT:\n"
        "- replace the recommended action\n"
        "- upgrade tentative advice into a confident fix\n"
        "- invent evidence, root causes, or validation steps\n"
        "- override confidence, mode, or degraded status\n"
        "- turn a single-ticket grounded answer into a list or broad generic guidance\n"
        "- repeat the recommended action in summary or why-this-matches text\n"
        "- repeat validation or next-step content\n"
        "- add generic troubleshooting filler like 'check logs' or 'verify configuration' unless the grounding already names the exact subsystem and reason\n"
        "You may:\n"
        "- simplify language\n"
        "- summarize the root issue in 1-2 short bullets\n"
        "- summarize why the evidence matches in 1-2 short bullets\n"
        "- acknowledge limited evidence honestly in one short confidence note\n"
        "- reuse the ticket or topic already established by the conversation context in the user question\n"
        "If mode is tentative_diagnostic or no_strong_match, preserve uncertainty clearly.\n"
        "If mode is tentative_diagnostic, do not phrase anything as a confirmed fix.\n"
        "If retrieval_mode is lexical_only or fallback_rules, explicitly mention that evidence quality is limited.\n"
        "Keep each bullet concise and engineer-friendly.\n"
        "Maximum lengths:\n"
        "- summary: 2 bullets\n"
        "- why_this_matches: 2 bullets\n"
        "- confidence_note: 1 short sentence\n"
        "JSON schema:\n"
        "{\n"
        '  "summary": ["short bullet", "short bullet"] | [],\n'
        '  "why_this_matches": ["short bullet", "short bullet"] | [],\n'
        '  "confidence_note": "short sentence or empty string"\n'
        "}\n"
        f"- Write all strings in language: {lang}.\n"
        f"- Greeting available if useful: {greeting}.\n"
        f"- User question: {question}\n"
        f"- Resolver grounding JSON:\n{json.dumps(grounding, ensure_ascii=True)}\n"
    )
