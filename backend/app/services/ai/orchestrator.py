"""Chat orchestration for ITSM assistant."""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import TicketCategory, TicketPriority, TicketStatus, UserRole
from app.schemas.ai import AIRecommendationOut, ChatRequest, ChatResponse, ClassificationRequest, ClassificationResponse, TicketDraft
from app.services.ai.analytics_queries import _answer_data_query
from app.services.ai.classifier import apply_category_guardrail, classify_ticket, classify_ticket_detailed, score_recommendations
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
    extract_recent_ticket_constraints,
    _is_explicit_ticket_create_request,
    _normalize_intent_text,
    _normalize_locale,
    _wants_active_only,
    _wants_open_only,
    detect_intent,
)
from app.services.ai.llm import extract_json, ollama_generate
from app.services.ai.prompts import build_chat_prompt
from app.services.ai.quickfix import append_solution
from app.services.jira_kb import build_jira_knowledge_block
from app.services.tickets import compute_stats, list_tickets_for_user, select_best_assignee
from app.services.users import list_assignees

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RoutingPlan:
    name: str
    intent: ChatIntent
    use_llm: bool
    use_kb: bool
    constraints: list[str] = field(default_factory=list)
    reason: str = ""


def build_routing_plan(
    question: str,
    *,
    intent: ChatIntent,
    create_requested: bool,
) -> RoutingPlan:
    if create_requested:
        return RoutingPlan(
            name="forced_create_ticket",
            intent=ChatIntent.create_ticket,
            use_llm=True,
            use_kb=True,
            reason="explicit_create_request",
        )

    if intent == ChatIntent.recent_ticket:
        constraints = extract_recent_ticket_constraints(question)
        if constraints:
            return RoutingPlan(
                name="recent_ticket_filtered",
                intent=intent,
                use_llm=True,
                use_kb=True,
                constraints=constraints,
                reason="recent_ticket_with_constraints",
            )
        return RoutingPlan(
            name="shortcut_recent_ticket",
            intent=intent,
            use_llm=False,
            use_kb=False,
            reason="plain_recent_ticket_no_constraints",
        )

    deterministic = {
        ChatIntent.most_used_tickets: "shortcut_most_used_tickets",
        ChatIntent.weekly_summary: "shortcut_weekly_summary",
        ChatIntent.critical_tickets: "shortcut_critical_tickets",
        ChatIntent.recurring_solutions: "shortcut_recurring_solutions",
    }
    if intent in deterministic:
        return RoutingPlan(
            name=deterministic[intent],
            intent=intent,
            use_llm=False,
            use_kb=False,
            reason=f"deterministic_{intent.value}",
        )

    if intent == ChatIntent.data_query:
        return RoutingPlan(
            name="structured_data_query",
            intent=intent,
            use_llm=False,
            use_kb=False,
            reason="query_looks_structured",
        )

    return RoutingPlan(
        name="general_llm",
        intent=intent,
        use_llm=True,
        use_kb=True,
        reason="default_general_flow",
    )


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


def _build_chat_text_fallback_prompt(
    *,
    question: str,
    lang: str,
    greeting: str,
    knowledge_section: str,
    assignee_list: list[str],
    stats: dict,
) -> str:
    language_name = "French" if lang == "fr" else "English"
    return (
        "You are an ITSM assistant. Answer in plain text only (no JSON).\n"
        "Think step by step internally, then provide a concise actionable response.\n"
        "KNOWLEDGE-FIRST POLICY:\n"
        "- If Knowledge Section has Jira matches, base classification and troubleshooting on those matches first.\n"
        "- Every recommendation must be grounded in retrieved comments or Jira fields when matches exist.\n"
        "- If Knowledge Section is empty or insufficient, use basic IT troubleshooting knowledge.\n"
        "- Never invent Jira keys, incidents, fixes, or past actions.\n"
        f"Language: {language_name}\n"
        f"Greeting to start with: {greeting}\n"
        f"Available assignees: {assignee_list}\n"
        f"Stats: {stats}\n"
        f"{knowledge_section}"
        f"User question: {question}\n"
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
    knowledge_block = build_jira_knowledge_block(
        question,
        lang=lang,
        limit=3,
        semantic_only=True,
        semantic_min_score=0.55,
    )
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
            notes = str(data.get("notes") or "").strip()
            ticket_payload = _safe_ticket_payload(data.get("ticket"))
            classification = data.get("classification")
            if isinstance(ticket_payload, dict) and isinstance(classification, dict):
                if not ticket_payload.get("priority") and isinstance(classification.get("priority"), str):
                    ticket_payload["priority"] = classification.get("priority")
                if not ticket_payload.get("category") and isinstance(classification.get("category"), str):
                    ticket_payload["category"] = classification.get("category")
            if not reply_text:
                reply_text = _fallback_reply_from_payload(data, lang=lang, greeting=greeting)
            if solution and action in {None, "none"} and solution.casefold() not in reply_text.casefold():
                reply_text = append_solution(reply_text, solution, lang=lang)
            if notes and notes.casefold() not in reply_text.casefold():
                reply_text = f"{reply_text}\n\n{notes}".strip()
            if not (reply_text or "").strip():
                reply_text = _fallback_reply_from_payload(data, lang=lang, greeting=greeting)
            return reply_text, action, ticket_payload

        raw_reply = str(reply or "").strip()
        should_retry_text = not raw_reply or raw_reply.startswith("{")
        if should_retry_text:
            try:
                raw_reply = ollama_generate(
                    _build_chat_text_fallback_prompt(
                        question=question,
                        lang=lang,
                        greeting=greeting,
                        knowledge_section=knowledge_section,
                        assignee_list=assignee_list,
                        stats=stats,
                    ),
                    json_mode=False,
                ).strip()
            except Exception as exc:
                logger.info("Ollama chat text fallback failed: %s", exc)
                raw_reply = str(reply or "").strip()

        if not raw_reply:
            raw_reply = (
                f"{greeting}, I could not produce a clear answer. Could you rephrase?"
                if lang == "en"
                else f"{greeting}, je n'ai pas pu formuler une reponse claire, pouvez-vous reformuler ?"
            )
        return raw_reply, None, None
    except Exception as exc:
        logger.warning("Ollama chat failed: %s", exc)
        error_reply = "LLM is unavailable. Please try again." if lang == "en" else "LLM indisponible. Reessayez."
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
        category = apply_category_guardrail(title, description, category)
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


def _ticket_prompt_lines(tickets: list, *, limit: int = 40) -> list[str]:
    return [
        f"{t.id} | {t.title} | {t.priority.value} | {t.status.value} | {t.category.value} | {t.assignee}"
        for t in tickets[:limit]
    ]


def _ticket_search_blob(ticket: Any) -> str:
    parts = [
        str(getattr(ticket, "id", "") or ""),
        str(getattr(ticket, "title", "") or ""),
        str(getattr(ticket, "description", "") or ""),
        str(getattr(ticket, "assignee", "") or ""),
        str(getattr(ticket, "reporter", "") or ""),
        str(getattr(ticket, "resolution", "") or ""),
    ]
    comments = getattr(ticket, "comments", None) or []
    for comment in comments:
        parts.append(str(getattr(comment, "author", "") or ""))
        parts.append(str(getattr(comment, "content", "") or ""))
    return _normalize_intent_text(" ".join(parts))


def _filter_recent_tickets_by_constraints(tickets: list, constraints: list[str]) -> list:
    if not constraints:
        return list(tickets)

    scored: list[tuple[int, dt.datetime, Any]] = []
    for ticket in tickets:
        searchable = _ticket_search_blob(ticket)
        if not searchable:
            continue
        score = sum(1 for constraint in constraints if constraint and constraint in searchable)
        if score <= 0:
            continue
        scored.append((score, _created_at_sort_value(getattr(ticket, "created_at", None)), ticket))

    scored.sort(key=lambda item: (item[0], item[1], str(getattr(item[2], "id", ""))), reverse=True)
    return [item[2] for item in scored]


def _recent_local_context(ticket: Any, *, lang: str) -> str:
    if ticket is None:
        return ""
    if lang == "fr":
        return (
            "Candidat local recent (a verifier avec contraintes): "
            f"{ticket.id} | {ticket.title} | {ticket.priority.value} | {ticket.status.value} | {ticket.category.value} | {ticket.assignee}"
        )
    return (
        "Recent local candidate (verify against constraints): "
        f"{ticket.id} | {ticket.title} | {ticket.priority.value} | {ticket.status.value} | {ticket.category.value} | {ticket.assignee}"
    )


def _build_ticket_draft_from_payload(
    *,
    ticket_payload: dict[str, Any],
    fallback_question: str,
    assignee_names: list[str],
    current_user,
) -> TicketDraft:
    title = str(ticket_payload.get("title") or fallback_question or "New ticket")
    description = str(ticket_payload.get("description") or fallback_question or title)
    try:
        priority = TicketPriority(ticket_payload.get("priority"))
        category = TicketCategory(ticket_payload.get("category"))
        category = apply_category_guardrail(title, description, category)
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
    return TicketDraft(
        title=title,
        description=description,
        priority=priority,
        category=category,
        tags=tags,
        assignee=assignee,
    )


def _normalize_recommendation_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for raw in value:
        text = str(raw or "").strip()
        if text:
            items.append(text)
    return items


def _prefer_translated_list(original: list[str], candidate: list[str]) -> list[str]:
    if len(candidate) != len(original):
        return original
    return candidate


def _translate_recommendation_groups(
    groups: dict[str, list[str]],
    *,
    lang: str,
) -> dict[str, list[str]]:
    if lang not in {"en", "fr"}:
        return groups
    if not any(groups.values()):
        return groups

    target_language = "English" if lang == "en" else "French"
    prompt = (
        "You are a technical translator for IT support recommendations.\n"
        "Return ONLY valid JSON with this schema exactly:\n"
        "{\n"
        '  "recommendations": ["..."],\n'
        '  "recommendations_embedding": ["..."],\n'
        '  "recommendations_llm": ["..."]\n'
        "}\n"
        f"Translate all recommendation strings to {target_language}.\n"
        "Rules:\n"
        "- Keep each array length unchanged.\n"
        "- Keep item order unchanged.\n"
        "- Keep technical terms, product names and acronyms accurate.\n"
        "- Keep concise, actionable support style.\n"
        "- Do not add or remove recommendations.\n"
        f"Input JSON:\n{json.dumps(groups, ensure_ascii=True)}\n"
    )
    try:
        translated_raw = ollama_generate(prompt, json_mode=True)
        translated = extract_json(translated_raw) or {}
        translated_main = _normalize_recommendation_list(translated.get("recommendations"))
        translated_embedding = _normalize_recommendation_list(translated.get("recommendations_embedding"))
        translated_llm = _normalize_recommendation_list(translated.get("recommendations_llm"))
        return {
            "recommendations": _prefer_translated_list(groups["recommendations"], translated_main),
            "recommendations_embedding": _prefer_translated_list(groups["recommendations_embedding"], translated_embedding),
            "recommendations_llm": _prefer_translated_list(groups["recommendations_llm"], translated_llm),
        }
    except Exception as exc:
        logger.info("Recommendation translation skipped; using source language: %s", exc)
        return groups


def handle_classify(payload: ClassificationRequest, db: Session) -> ClassificationResponse:
    lang = _normalize_locale(payload.locale)
    details = classify_ticket_detailed(payload.title, payload.description)
    priority = details["priority"]
    category = details["category"]
    translated_groups = _translate_recommendation_groups(
        {
            "recommendations": list(details.get("recommendations") or []),
            "recommendations_embedding": list(details.get("recommendations_embedding") or []),
            "recommendations_llm": list(details.get("recommendations_llm") or []),
        },
        lang=lang,
    )
    recommendations = translated_groups["recommendations"]
    recommendations_embedding = translated_groups["recommendations_embedding"]
    recommendations_llm = translated_groups["recommendations_llm"]
    recommendation_mode = str(details.get("recommendation_mode") or "llm")
    assignee = select_best_assignee(db, category=category, priority=priority)
    if recommendation_mode in {"embedding", "hybrid"}:
        scored = score_recommendations(recommendations, start_confidence=90, rank_decay=6, floor=55, ceiling=97)
    else:
        scored = score_recommendations(recommendations, start_confidence=84, rank_decay=8, floor=56, ceiling=92)
    scored_embedding = score_recommendations(recommendations_embedding, start_confidence=90, rank_decay=6, floor=55, ceiling=97)
    scored_llm = score_recommendations(recommendations_llm, start_confidence=82, rank_decay=8, floor=50, ceiling=93)
    return ClassificationResponse(
        priority=priority,
        category=category,
        recommendations=recommendations,
        recommendations_scored=[AIRecommendationOut(text=str(item["text"]), confidence=int(item["confidence"])) for item in scored],
        recommendations_embedding=recommendations_embedding,
        recommendations_embedding_scored=[
            AIRecommendationOut(text=str(item["text"]), confidence=int(item["confidence"])) for item in scored_embedding
        ],
        recommendations_llm=recommendations_llm,
        recommendations_llm_scored=[
            AIRecommendationOut(text=str(item["text"]), confidence=int(item["confidence"])) for item in scored_llm
        ],
        recommendation_mode=recommendation_mode,
        similarity_found=bool(details.get("similarity_found")),
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
    plan = build_routing_plan(last_question, intent=intent, create_requested=create_requested)
    logger.info(
        "AI routing plan selected: %s (intent=%s, constraints=%s, reason=%s)",
        plan.name,
        plan.intent.value,
        plan.constraints,
        plan.reason,
    )
    top = _ticket_prompt_lines(tickets)

    if plan.name == "forced_create_ticket":
        return _build_forced_ai_ticket_draft(
            question=last_question,
            lang=lang,
            db=db,
            stats=stats,
            assignee_names=assignee_names,
            current_user=current_user,
            top=top,
        )

    if plan.name == "shortcut_recent_ticket":
        open_only = _wants_open_only(lowered)
        pool = [t for t in tickets if t.status == TicketStatus.open] if open_only else tickets
        recent = pool[0] if pool else None
        reply = _format_most_recent_ticket(recent, lang, open_only=open_only)
        summary = _ticket_to_summary(recent, lang)
        return ChatResponse(reply=reply, action="show_ticket" if summary else None, ticket=summary)

    if plan.name == "shortcut_most_used_tickets":
        reply = _format_most_used_tickets(tickets, lang)
        return ChatResponse(reply=reply, action=None, ticket=None)

    if plan.name == "shortcut_weekly_summary":
        reply = _format_weekly_summary(tickets, stats, lang)
        return ChatResponse(reply=reply, action=None, ticket=None)

    if plan.name == "shortcut_critical_tickets":
        active_only = _wants_active_only(lowered)
        critical = [t for t in tickets if t.priority == TicketPriority.critical]
        if active_only:
            critical = [t for t in critical if t.status in ACTIVE_STATUSES]
        reply = _format_critical_tickets(critical, lang, active_only=active_only)
        summary = _ticket_to_summary(critical[0], lang) if critical else None
        return ChatResponse(reply=reply, action="show_ticket" if summary else None, ticket=summary)

    if plan.name == "shortcut_recurring_solutions":
        reply = _format_recurring_solutions(tickets, lang, last_question)
        return ChatResponse(reply=reply, action=None, ticket=None)

    if plan.name == "structured_data_query":
        structured_answer = _answer_data_query(last_question, tickets, lang, assignee_names)
        if structured_answer:
            reply, action, ticket = structured_answer
            return ChatResponse(reply=reply, action=action, ticket=ticket)
        logger.info("AI routing fallback to general_llm because structured_data_query returned no answer.")
        plan = RoutingPlan(
            name="general_llm",
            intent=ChatIntent.general,
            use_llm=True,
            use_kb=True,
            reason="structured_data_query_no_match",
        )

    question_for_llm = last_question
    top_for_llm = top

    if plan.name == "recent_ticket_filtered":
        open_only = _wants_open_only(lowered)
        pool = [t for t in tickets if t.status == TicketStatus.open] if open_only else tickets
        filtered_pool = _filter_recent_tickets_by_constraints(pool, plan.constraints)
        best_recent = filtered_pool[0] if filtered_pool else None
        logger.info(
            "AI routing recent_ticket_filtered: open_only=%s local_matches=%s constraints=%s",
            open_only,
            len(filtered_pool),
            plan.constraints,
        )

        if best_recent is not None:
            question_for_llm = f"{last_question}\n\n{_recent_local_context(best_recent, lang=lang)}"
            filtered_ids = {str(getattr(ticket, "id", "")) for ticket in filtered_pool}
            remainder = [ticket for ticket in tickets if str(getattr(ticket, "id", "")) not in filtered_ids]
            top_for_llm = _ticket_prompt_lines([*filtered_pool[:60], *remainder[:60]], limit=120)
        elif lang == "fr":
            question_for_llm = (
                f"{last_question}\n\n"
                "Aucun ticket local correspondant aux contraintes n'a ete trouve. "
                "Analysez avec prudence et utilisez uniquement des elements verifies."
            )
        else:
            question_for_llm = (
                f"{last_question}\n\n"
                "No local ticket matched these constraints. "
                "Analyze carefully and rely only on verifiable information."
            )

    reply, action, ticket_payload = build_chat_reply(
        question_for_llm,
        stats,
        top_for_llm,
        locale=payload.locale,
        assignees=assignee_names,
    )

    if action == "create_ticket" and not create_requested:
        # Keep the draft payload available as a preview/create option,
        # but avoid forcing explicit create action when intent is ambiguous.
        action = "none"

    ticket: TicketDraft | None = None
    if isinstance(ticket_payload, dict):
        ticket = _build_ticket_draft_from_payload(
            ticket_payload=ticket_payload,
            fallback_question=last_question,
            assignee_names=assignee_names,
            current_user=current_user,
        )

    return ChatResponse(reply=reply, action=action, ticket=ticket)
