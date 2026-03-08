"""Service helpers for recommendation queries."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.enums import (
    ProblemStatus,
    RecommendationImpact,
    RecommendationType,
    TicketPriority,
    TicketStatus,
)
from app.models.problem import Problem
from app.models.recommendation import Recommendation
from app.models.ticket import Ticket
from app.models.user import User
from app.services.ai.classifier import classify_ticket_detailed, score_recommendations
from app.services.problems import build_problem_ai_suggestions
from app.services.tickets import list_tickets_for_user

logger = logging.getLogger(__name__)

_ACTIVE_TICKET_STATUSES = {
    TicketStatus.open,
    TicketStatus.in_progress,
    TicketStatus.waiting_for_customer,
    TicketStatus.waiting_for_support_vendor,
    TicketStatus.pending,
}
_ACTIVE_PROBLEM_STATUSES = {
    ProblemStatus.open,
    ProblemStatus.investigating,
    ProblemStatus.known_error,
}
_MAX_CRITICAL_TICKETS = 3
_MAX_ACTIVE_PROBLEMS = 2
_MAX_RECOMMENDATIONS = 18


@dataclass(slots=True)
class RecommendationView:
    id: str
    type: RecommendationType
    title: str
    description: str
    related_tickets: list[str]
    confidence: int
    impact: RecommendationImpact
    created_at: dt.datetime


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _clamp_confidence(value: int, *, floor: int = 50, ceiling: int = 97) -> int:
    return max(floor, min(ceiling, int(value)))


def _ai_rec_id(*parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10].upper()
    return f"AI-{digest}"


def _impact_for_ticket(priority: TicketPriority) -> RecommendationImpact:
    if priority == TicketPriority.critical:
        return RecommendationImpact.high
    if priority == TicketPriority.high:
        return RecommendationImpact.high
    if priority == TicketPriority.medium:
        return RecommendationImpact.medium
    return RecommendationImpact.low


def _is_active_ticket(ticket: Ticket) -> bool:
    return ticket.status in _ACTIVE_TICKET_STATUSES


def _legacy_recommendations(db: Session, *, visible_ticket_ids: set[str]) -> list[Recommendation]:
    rows = db.query(Recommendation).order_by(Recommendation.created_at.desc()).all()
    return [
        row
        for row in rows
        if not row.related_tickets
        or any(ticket_id in visible_ticket_ids for ticket_id in row.related_tickets)
    ]


def _build_ticket_ai_recommendations(ticket: Ticket) -> list[RecommendationView]:
    try:
        details = classify_ticket_detailed(ticket.title, ticket.description)
    except Exception as exc:  # noqa: BLE001
        logger.info("AI classify failed for recommendation ticket %s: %s", ticket.id, exc)
        return []

    mode = str(details.get("recommendation_mode") or "llm")
    main_recommendations = [str(item).strip() for item in list(details.get("recommendations") or []) if str(item).strip()]
    if mode in {"embedding", "hybrid"}:
        scored = score_recommendations(main_recommendations, start_confidence=90, rank_decay=6, floor=55, ceiling=97)
    else:
        scored = score_recommendations(main_recommendations, start_confidence=84, rank_decay=8, floor=56, ceiling=92)
    if not scored and main_recommendations:
        scored = [{"text": main_recommendations[0], "confidence": 70}]
    if not scored:
        return []

    first = scored[0]
    first_text = str(first.get("text") or "").strip()
    first_confidence = _clamp_confidence(int(first.get("confidence") or 70))
    if not first_text:
        return []

    created_at = ticket.updated_at or ticket.created_at or _utcnow()
    impact = _impact_for_ticket(ticket.priority)
    recs: list[RecommendationView] = []

    if bool(details.get("similarity_found")):
        recs.append(
            RecommendationView(
                id=_ai_rec_id("ticket", ticket.id, "pattern"),
                type=RecommendationType.pattern,
                title=f"AI pattern signal for {ticket.id}",
                description=f"RAG found similar incidents for {ticket.id}. Action focus: {first_text}",
                related_tickets=[ticket.id],
                confidence=_clamp_confidence(first_confidence + 3),
                impact=impact,
                created_at=created_at,
            )
        )

    suggested_priority = details.get("priority")
    if isinstance(suggested_priority, TicketPriority) and suggested_priority != ticket.priority:
        recs.append(
            RecommendationView(
                id=_ai_rec_id("ticket", ticket.id, "priority"),
                type=RecommendationType.priority,
                title=f"AI triage priority check for {ticket.id}",
                description=(
                    f"Current priority is {ticket.priority.value}. "
                    f"RAG + LLM triage suggests {suggested_priority.value}. "
                    f"Supporting action: {first_text}"
                ),
                related_tickets=[ticket.id],
                confidence=_clamp_confidence(first_confidence),
                impact=RecommendationImpact.high,
                created_at=created_at,
            )
        )

    recs.append(
        RecommendationView(
            id=_ai_rec_id("ticket", ticket.id, "solution"),
            type=RecommendationType.solution,
            title=f"AI solution recommendation for {ticket.id}",
            description=first_text,
            related_tickets=[ticket.id],
            confidence=_clamp_confidence(first_confidence),
            impact=impact,
            created_at=created_at,
        )
    )

    workflow_text = ""
    workflow_confidence = max(55, first_confidence - 4)
    if len(scored) > 1:
        workflow_text = str(scored[1].get("text") or "").strip()
        workflow_confidence = _clamp_confidence(int(scored[1].get("confidence") or workflow_confidence))
    if not workflow_text:
        workflow_text = (
            f"Use the same RAG-backed validation workflow for {ticket.id}: "
            "collect timeline evidence, apply the action, then verify user impact before closure."
        )
    recs.append(
        RecommendationView(
            id=_ai_rec_id("ticket", ticket.id, "workflow"),
            type=RecommendationType.workflow,
            title=f"AI workflow recommendation for {ticket.id}",
            description=workflow_text,
            related_tickets=[ticket.id],
            confidence=_clamp_confidence(workflow_confidence),
            impact=RecommendationImpact.medium if impact == RecommendationImpact.high else impact,
            created_at=created_at,
        )
    )
    return recs


def _build_problem_ai_recommendations(
    db: Session,
    *,
    problem: Problem,
    linked_tickets: list[Ticket],
) -> list[RecommendationView]:
    if not linked_tickets:
        return []
    try:
        payload = build_problem_ai_suggestions(db, problem, tickets=linked_tickets, limit=4)
    except Exception as exc:  # noqa: BLE001
        logger.info("Problem AI suggestions failed for %s: %s", problem.id, exc)
        return []

    scored = list(payload.get("suggestions_scored") or [])
    if not scored:
        return []

    created_at = problem.updated_at or problem.created_at or _utcnow()
    related_ticket_ids = [ticket.id for ticket in linked_tickets][:8]
    has_critical_linked = any(
        ticket.priority == TicketPriority.critical and _is_active_ticket(ticket)
        for ticket in linked_tickets
    )
    first = scored[0]
    first_text = str(first.get("text") or "").strip()
    first_confidence = _clamp_confidence(int(first.get("confidence") or 76))
    if not first_text:
        return []

    recs: list[RecommendationView] = [
        RecommendationView(
            id=_ai_rec_id("problem", problem.id, "pattern"),
            type=RecommendationType.pattern,
            title=f"AI pattern recommendation for {problem.id}",
            description=(
                f"Problem {problem.id} has {int(problem.active_count)} active linked tickets "
                f"({int(problem.occurrences_count)} occurrences). {first_text}"
            ),
            related_tickets=related_ticket_ids,
            confidence=_clamp_confidence(first_confidence + 2),
            impact=RecommendationImpact.high if has_critical_linked or int(problem.active_count) >= 3 else RecommendationImpact.medium,
            created_at=created_at,
        )
    ]

    permanent_fix = str(payload.get("permanent_fix_suggestion") or "").strip()
    workaround = str(payload.get("workaround_suggestion") or "").strip()
    solution_text = permanent_fix or workaround or first_text
    solution_conf = payload.get("permanent_fix_confidence") if permanent_fix else payload.get("workaround_confidence")
    if solution_conf is None:
        solution_conf = first_confidence
    recs.append(
        RecommendationView(
            id=_ai_rec_id("problem", problem.id, "solution"),
            type=RecommendationType.solution,
            title=f"AI solution recommendation for {problem.id}",
            description=solution_text,
            related_tickets=related_ticket_ids,
            confidence=_clamp_confidence(int(solution_conf)),
            impact=RecommendationImpact.high if permanent_fix else RecommendationImpact.medium,
            created_at=created_at,
        )
    )

    workflow_text = ""
    workflow_conf = max(56, first_confidence - 5)
    if len(scored) > 1:
        workflow_text = str(scored[1].get("text") or "").strip()
        workflow_conf = _clamp_confidence(int(scored[1].get("confidence") or workflow_conf))
    if not workflow_text:
        workflow_text = (
            "Run the problem workflow with RCA verification, temporary containment, "
            "and post-fix monitoring checkpoints."
        )
    recs.append(
        RecommendationView(
            id=_ai_rec_id("problem", problem.id, "workflow"),
            type=RecommendationType.workflow,
            title=f"AI workflow recommendation for {problem.id}",
            description=workflow_text,
            related_tickets=related_ticket_ids,
            confidence=_clamp_confidence(workflow_conf),
            impact=RecommendationImpact.medium,
            created_at=created_at,
        )
    )

    if has_critical_linked:
        recs.append(
            RecommendationView(
                id=_ai_rec_id("problem", problem.id, "priority"),
                type=RecommendationType.priority,
                title=f"AI priority recommendation for {problem.id}",
                description=(
                    "Critical linked incidents are still active. Prioritize this problem stream for immediate triage "
                    f"and escalation. Evidence-backed action: {first_text}"
                ),
                related_tickets=related_ticket_ids,
                confidence=_clamp_confidence(first_confidence),
                impact=RecommendationImpact.high,
                created_at=created_at,
            )
        )

    return recs


def _dedupe_rows(rows: list[RecommendationView]) -> list[RecommendationView]:
    seen: set[tuple[str, str]] = set()
    unique: list[RecommendationView] = []
    for row in rows:
        key = (row.type.value, row.title.strip().casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def list_recommendations(db: Session, user: User) -> list[Recommendation | RecommendationView]:
    visible_tickets = list_tickets_for_user(db, user)
    visible_ticket_ids = {ticket.id for ticket in visible_tickets}
    if not visible_tickets:
        return _legacy_recommendations(db, visible_ticket_ids=visible_ticket_ids)

    ai_rows: list[RecommendationView] = []

    critical_active = sorted(
        [
            ticket
            for ticket in visible_tickets
            if ticket.priority == TicketPriority.critical and _is_active_ticket(ticket)
        ],
        key=lambda item: (item.updated_at or item.created_at or _utcnow()),
        reverse=True,
    )
    for ticket in critical_active[:_MAX_CRITICAL_TICKETS]:
        ai_rows.extend(_build_ticket_ai_recommendations(ticket))

    linked_by_problem: dict[str, list[Ticket]] = {}
    for ticket in visible_tickets:
        if ticket.problem_id:
            linked_by_problem.setdefault(ticket.problem_id, []).append(ticket)
    if linked_by_problem:
        problem_ids = list(linked_by_problem.keys())
        problem_rows = (
            db.query(Problem)
            .filter(Problem.id.in_(problem_ids))
            .order_by(Problem.updated_at.desc())
            .all()
        )
        active_problems = [problem for problem in problem_rows if problem.status in _ACTIVE_PROBLEM_STATUSES]
        active_problems.sort(
            key=lambda item: (int(item.active_count), int(item.occurrences_count), item.updated_at or item.created_at or _utcnow()),
            reverse=True,
        )
        for problem in active_problems[:_MAX_ACTIVE_PROBLEMS]:
            ai_rows.extend(
                _build_problem_ai_recommendations(
                    db,
                    problem=problem,
                    linked_tickets=linked_by_problem.get(problem.id, []),
                )
            )

    ai_rows = _dedupe_rows(ai_rows)
    ai_rows.sort(
        key=lambda item: (item.created_at or _utcnow(), int(item.confidence)),
        reverse=True,
    )
    if ai_rows:
        return ai_rows[:_MAX_RECOMMENDATIONS]
    return _legacy_recommendations(db, visible_ticket_ids=visible_ticket_ids)
