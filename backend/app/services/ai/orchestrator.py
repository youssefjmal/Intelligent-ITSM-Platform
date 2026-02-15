"""Chat orchestration for ITSM assistant."""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import TicketCategory, TicketPriority, TicketStatus, UserRole
from app.schemas.ai import AIRecommendationOut, ChatRequest, ChatResponse, ClassificationRequest, ClassificationResponse, TicketDraft
from app.services.ai.analytics_queries import _answer_data_query
from app.services.ai.classifier import classify_ticket, score_recommendations
from app.services.ai.formatters import (
    _format_critical_tickets,
    _format_most_recent_ticket,
    _format_most_used_tickets,
    _format_recurring_solutions,
    _format_weekly_summary,
    _ticket_to_summary,
)
from app.services.ai.intents import (
    ACTIVE_STATUSES,
    ChatIntent,
    _is_explicit_ticket_create_request,
    _normalize_intent_text,
    _normalize_locale,
    _wants_active_only,
    _wants_open_only,
    detect_intent,
)
from app.services.ai.llm import extract_json, ollama_generate
from app.services.ai.prompts import build_chat_prompt
from app.services.ai.quickfix import append_solution, explicit_ticket_request, suggest_quick_fix
from app.services.jira_kb import build_jira_knowledge_block
from app.services.tickets import compute_stats, list_tickets_for_user, select_best_assignee
from app.services.users import list_assignees

logger = logging.getLogger(__name__)


def _time_greeting(lang: str) -> str:
    hour = dt.datetime.now().hour
    is_evening = hour >= 18 or hour < 5
    if lang == "fr":
        return "Bonsoir" if is_evening else "Bonjour"
    return "Good evening" if is_evening else "Good morning"


def _normalize_action(action: Any) -> str | None:
    if not isinstance(action, str):
        return None
    value = action.strip().lower()
    if value in {"create_ticket", "none"}:
        return value
    return None


def _solution_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip()).strip()
    return ""


def _safe_ticket_payload(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _fallback_reply_from_payload(data: dict[str, Any], *, lang: str, greeting: str) -> str:
    solution = _solution_text(data.get("solution"))
    if solution:
        return f"{greeting}, {solution}"

    ticket_payload = _safe_ticket_payload(data.get("ticket"))
    title = str((ticket_payload or {}).get("title") or "").strip()
    action = _normalize_action(data.get("action"))
    if action == "create_ticket":
        if lang == "fr":
            return f"{greeting}, brouillon de ticket prepare{': ' + title if title else '.'}"
        return f"{greeting}, ticket draft prepared{': ' + title if title else '.'}"
    if title:
        if lang == "fr":
            return f"{greeting}, voici le resultat analyse: {title}"
        return f"{greeting}, here is the analyzed result: {title}"

    return (
        f"{greeting}, je n'ai pas pu formuler une reponse claire, pouvez-vous reformuler ?"
        if lang == "fr"
        else f"{greeting}, I could not produce a clear answer. Could you rephrase?"
    )


def build_chat_reply(
    question: str,
    stats: dict,
    top_tickets: list[str],
    *,
    locale: str | None = None,
    assignees: list[str] | None = None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    lang = _normalize_locale(locale)
    greeting = _time_greeting(lang)
    assignee_list = assignees or []
    wants_ticket = explicit_ticket_request(question)
    knowledge_block = build_jira_knowledge_block(question, lang=lang)
    knowledge_section = f"{knowledge_block}\n\n" if knowledge_block else ""
    prompt = build_chat_prompt(
        question=question,
        knowledge_section=knowledge_section,
        lang=lang,
        greeting=greeting,
        assignee_list=assignee_list,
        stats=stats,
        top_tickets=top_tickets,
    )

    try:
        reply = ollama_generate(prompt, json_mode=True)
        data = extract_json(reply)
        if data:
            reply_text = str(data.get("reply", "") or "").strip()
            action = _normalize_action(data.get("action"))
            solution = _solution_text(data.get("solution"))
            ticket_payload = _safe_ticket_payload(data.get("ticket"))
            if not reply_text:
                reply_text = _fallback_reply_from_payload(data, lang=lang, greeting=greeting)
            quick_fix = suggest_quick_fix(question, lang=lang)
            if quick_fix and action == "create_ticket" and not wants_ticket:
                action = "none"
                ticket_payload = None
                reply_text = append_solution(reply_text, quick_fix, lang=lang)
            if solution and action in {None, "none"} and solution.casefold() not in reply_text.casefold():
                reply_text = append_solution(reply_text, solution, lang=lang)
            elif action in {None, "none"} and quick_fix:
                reply_text = append_solution(reply_text, quick_fix, lang=lang)
            return reply_text, action, ticket_payload

        quick_fix = suggest_quick_fix(question, lang=lang)
        if quick_fix:
            reply = append_solution(str(reply), quick_fix, lang=lang)
        return reply, None, None
    except Exception as exc:
        logger.warning("Ollama chat failed: %s", exc)
        error_reply = "LLM is unavailable. Please try again." if lang == "en" else "LLM indisponible. Reessayez."
        quick_fix = suggest_quick_fix(question, lang=lang)
        if quick_fix:
            error_reply = append_solution(error_reply, quick_fix, lang=lang)
        return error_reply, None, None


def _extract_create_subject(question: str, *, lang: str) -> str:
    raw = (question or "").strip()
    if not raw:
        return "New ITSM request" if lang == "en" else "Nouvelle demande ITSM"

    normalized = _normalize_intent_text(raw)
    patterns = [
        r"^(please\s+)?(create|generate|draft|open|raise|log|submit)\s+(a\s+)?(new\s+)?(ticket|incident)\s*(about|for|regarding)?\s*",
        r"^(je\s+veux\s+)?(creer|genere?r|ouvrir|declarer|signaler)\s+(un\s+)?(nouveau\s+)?(ticket|incident)\s*(sur|pour|concernant)?\s*",
        r"^je\s+vais\s+creer\s+un\s+ticket\s*(sur|pour|concernant)?\s*",
    ]
    for pattern in patterns:
        normalized = re.sub(pattern, "", normalized).strip(" .:-")
    if not normalized:
        return "New ITSM request" if lang == "en" else "Nouvelle demande ITSM"
    words = normalized.split()
    subject = " ".join(words[:14]).strip()
    if not subject:
        return "New ITSM request" if lang == "en" else "Nouvelle demande ITSM"
    return subject[:110]


def _title_case_words(text: str) -> str:
    words = [word for word in (text or "").split() if word]
    return " ".join(word[:1].upper() + word[1:] for word in words)


def _build_forced_ai_ticket_draft(
    *,
    question: str,
    lang: str,
    db: Session,
    stats: dict,
    assignee_names: list[str],
    current_user,
    top: list[str],
) -> ChatResponse:
    force_prompt = (
        (
            "Generate one complete ITSM ticket draft from this user message. "
            "Return action=create_ticket with title, detailed description, priority, category, tags and assignee when possible.\n"
            f"User message: {question}"
        )
        if lang == "en"
        else (
            "Genere un brouillon complet de ticket ITSM a partir du message utilisateur. "
            "Retourne action=create_ticket avec titre, description detaillee, priorite, categorie, tags et assigne si possible.\n"
            f"Message utilisateur: {question}"
        )
    )
    _reply, _action, payload = build_chat_reply(
        force_prompt,
        stats,
        top,
        locale=lang,
        assignees=assignee_names,
    )

    data = payload if isinstance(payload, dict) else {}
    subject = _extract_create_subject(question, lang=lang)
    subject_title = _title_case_words(subject)
    default_title = (
        f"New ticket - {subject_title}"
        if lang == "en"
        else f"Nouveau ticket - {subject_title}"
    )[:120]
    default_description = (
        "Ticket draft generated by AI assistant.\n"
        f"User request: {question or subject}\n"
        f"Context: {subject_title}\n"
        "Please review scope, impacted users and expected outcome before submission."
        if lang == "en"
        else
        "Brouillon de ticket genere par l'assistant IA.\n"
        f"Demande utilisateur: {question or subject}\n"
        f"Contexte: {subject_title}\n"
        "Veuillez confirmer le scope, les utilisateurs impactes et le resultat attendu avant soumission."
    )

    title = str(data.get("title") or default_title).strip()[:120]
    description = str(data.get("description") or default_description).strip()
    if len(description) < 5:
        description = default_description

    try:
        priority = TicketPriority(data.get("priority"))
        category = TicketCategory(data.get("category"))
    except Exception:
        priority, category, _ = classify_ticket(title, description)

    assignee = data.get("assignee")
    if isinstance(assignee, str):
        assignee = assignee.strip()
    else:
        assignee = None
    if assignee and assignee_names and assignee not in assignee_names:
        assignee = None
    if not assignee:
        assignee = select_best_assignee(db, category=category, priority=priority)
    if not assignee:
        if getattr(current_user, "role", None) in {UserRole.admin, UserRole.agent}:
            assignee = current_user.name
        elif assignee_names:
            assignee = assignee_names[0]

    tags = data.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
    if "ai-draft" not in clean_tags:
        clean_tags.append("ai-draft")
    if len(clean_tags) > 10:
        clean_tags = clean_tags[:10]

    draft = TicketDraft(
        title=title,
        description=description,
        priority=priority,
        category=category,
        tags=clean_tags,
        assignee=assignee,
    )
    response_text = (
        "AI ticket draft generated. Review it and click Create ticket."
        if lang == "en"
        else "Brouillon de ticket IA genere. Verifiez-le puis cliquez sur Creer le ticket."
    )
    return ChatResponse(reply=response_text, action="create_ticket", ticket=draft)


def _created_at_sort_value(value: object) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def handle_classify(payload: ClassificationRequest, db: Session) -> ClassificationResponse:
    priority, category, recommendations = classify_ticket(payload.title, payload.description)
    assignee = select_best_assignee(db, category=category, priority=priority)
    scored = score_recommendations(recommendations)
    return ClassificationResponse(
        priority=priority,
        category=category,
        recommendations=recommendations,
        recommendations_scored=[AIRecommendationOut(text=str(item["text"]), confidence=int(item["confidence"])) for item in scored],
        assignee=assignee,
    )


def handle_chat(payload: ChatRequest, db: Session, current_user) -> ChatResponse:
    tickets = list_tickets_for_user(db, current_user)
    tickets = sorted(
        tickets,
        key=lambda item: (_created_at_sort_value(getattr(item, "created_at", None)), str(getattr(item, "id", ""))),
        reverse=True,
    )
    stats = compute_stats(tickets)
    last_question = payload.messages[-1].content if payload.messages else ""
    lang = _normalize_locale(payload.locale)
    lowered = _normalize_intent_text(last_question or "")
    assignees = list_assignees(db)
    assignee_names = [u.name for u in assignees]
    create_requested = _is_explicit_ticket_create_request(last_question or "")
    intent = detect_intent(last_question or "")
    top = [
        f"{t.id} | {t.title} | {t.priority.value} | {t.status.value} | {t.category.value} | {t.assignee}"
        for t in tickets[:120]
    ]

    if create_requested:
        return _build_forced_ai_ticket_draft(
            question=last_question,
            lang=lang,
            db=db,
            stats=stats,
            assignee_names=assignee_names,
            current_user=current_user,
            top=top,
        )

    if intent == ChatIntent.recent_ticket:
        open_only = _wants_open_only(lowered)
        pool = [t for t in tickets if t.status == TicketStatus.open] if open_only else tickets
        recent = pool[0] if pool else None
        reply = _format_most_recent_ticket(recent, lang, open_only=open_only)
        summary = _ticket_to_summary(recent, lang)
        return ChatResponse(reply=reply, action="show_ticket" if summary else None, ticket=summary)

    if intent == ChatIntent.most_used_tickets:
        reply = _format_most_used_tickets(tickets, lang)
        return ChatResponse(reply=reply, action=None, ticket=None)

    if intent == ChatIntent.weekly_summary:
        reply = _format_weekly_summary(tickets, stats, lang)
        return ChatResponse(reply=reply, action=None, ticket=None)

    if intent == ChatIntent.critical_tickets:
        active_only = _wants_active_only(lowered)
        critical = [t for t in tickets if t.priority == TicketPriority.critical]
        if active_only:
            critical = [t for t in critical if t.status in ACTIVE_STATUSES]
        reply = _format_critical_tickets(critical, lang, active_only=active_only)
        summary = _ticket_to_summary(critical[0], lang) if critical else None
        return ChatResponse(reply=reply, action="show_ticket" if summary else None, ticket=summary)

    if intent == ChatIntent.recurring_solutions:
        reply = _format_recurring_solutions(tickets, lang, last_question)
        return ChatResponse(reply=reply, action=None, ticket=None)

    structured_answer = _answer_data_query(last_question, tickets, lang, assignee_names)
    if structured_answer:
        reply, action, ticket = structured_answer
        return ChatResponse(reply=reply, action=action, ticket=ticket)

    reply, action, ticket_payload = build_chat_reply(
        last_question,
        stats,
        top,
        locale=payload.locale,
        assignees=assignee_names,
    )

    if action == "create_ticket" and not create_requested:
        # Keep the draft payload available as a preview/create option,
        # but avoid forcing explicit create action when intent is ambiguous.
        action = "none"

    ticket: TicketDraft | None = None
    if isinstance(ticket_payload, dict):
        title = str(ticket_payload.get("title") or last_question or "New ticket")
        description = str(ticket_payload.get("description") or last_question or title)
        try:
            priority = TicketPriority(ticket_payload.get("priority"))
            category = TicketCategory(ticket_payload.get("category"))
        except Exception:
            priority, category, _ = classify_ticket(title, description)
        tags = ticket_payload.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        assignee = ticket_payload.get("assignee")
        if assignee and assignee_names and assignee not in assignee_names:
            assignee = None
        if not assignee:
            if getattr(current_user, "role", None) in {UserRole.admin, UserRole.agent}:
                assignee = current_user.name
            elif assignee_names:
                assignee = assignee_names[0]
        ticket = TicketDraft(
            title=title,
            description=description,
            priority=priority,
            category=category,
            tags=tags,
            assignee=assignee,
        )

    return ChatResponse(reply=reply, action=action, ticket=ticket)
