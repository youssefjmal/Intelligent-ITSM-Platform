"""Problem management API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.rate_limit import rate_limit
from app.core.rbac import can_view_ticket
from app.db.session import get_db
from app.models.enums import ProblemStatus, TicketCategory, UserRole
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.problem import (
    ProblemAISuggestionItem,
    ProblemAISuggestionsOut,
    ProblemAssigneeUpdateRequest,
    ProblemAssigneeUpdateResponse,
    ProblemDetailOut,
    ProblemDetectRequest,
    ProblemDetectResponse,
    ProblemLinkResponse,
    ProblemOut,
    ProblemTicketOut,
    ProblemUpdate,
    ResolveLinkedTicketsRequest,
    ResolveLinkedTicketsResponse,
)
from app.services.problems import (
    assign_problem_assignee,
    build_problem_ai_suggestions,
    derive_problem_assignee,
    detect_problems,
    get_problem,
    link_ticket,
    list_problems,
    resolve_linked_tickets,
    unlink_ticket,
    update_problem,
)

router = APIRouter(dependencies=[Depends(rate_limit()), Depends(get_current_user)])


def _visible_tickets(problem, *, user: User) -> list:  # noqa: ANN001
    if user.role in {UserRole.admin, UserRole.agent}:
        return list(problem.tickets or [])
    return [ticket for ticket in (problem.tickets or []) if can_view_ticket(user, ticket)]


def _to_out(problem, *, user: User) -> ProblemOut:  # noqa: ANN001
    visible = _visible_tickets(problem, user=user)
    return ProblemOut(
        id=problem.id,
        title=problem.title,
        category=problem.category,
        status=problem.status,
        created_at=problem.created_at,
        updated_at=problem.updated_at,
        last_seen_at=problem.last_seen_at,
        resolved_at=problem.resolved_at,
        occurrences_count=problem.occurrences_count,
        active_count=problem.active_count,
        root_cause=problem.root_cause,
        workaround=problem.workaround,
        permanent_fix=problem.permanent_fix,
        similarity_key=problem.similarity_key,
        assignee=derive_problem_assignee(problem, tickets=visible),
    )


def _to_detail(problem, *, user: User) -> ProblemDetailOut:  # noqa: ANN001
    visible = _visible_tickets(problem, user=user)
    return ProblemDetailOut(
        id=problem.id,
        title=problem.title,
        category=problem.category,
        status=problem.status,
        created_at=problem.created_at,
        updated_at=problem.updated_at,
        last_seen_at=problem.last_seen_at,
        resolved_at=problem.resolved_at,
        occurrences_count=problem.occurrences_count,
        active_count=problem.active_count,
        root_cause=problem.root_cause,
        workaround=problem.workaround,
        permanent_fix=problem.permanent_fix,
        similarity_key=problem.similarity_key,
        assignee=derive_problem_assignee(problem, tickets=visible),
        tickets=[
            ProblemTicketOut(
                id=ticket.id,
                title=ticket.title,
                status=ticket.status.value,
                assignee=ticket.assignee,
                reporter=ticket.reporter,
                created_at=ticket.created_at,
                updated_at=ticket.updated_at,
            )
            for ticket in sorted(visible, key=lambda item: item.updated_at, reverse=True)
        ],
        ai_suggestions=[],
    )


@router.get("/problems", response_model=list[ProblemOut])
def get_problems(
    status: ProblemStatus | None = Query(default=None),
    category: TicketCategory | None = Query(default=None),
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProblemOut]:
    records = list_problems(db, status=status, category=category, active_only=active_only)
    if not records and current_user.role in {UserRole.admin, UserRole.agent}:
        detect_problems(db, window_days=3, min_count=5)
        records = list_problems(db, status=status, category=category, active_only=active_only)

    scoped: list[ProblemOut] = []
    for record in records:
        visible = _visible_tickets(record, user=current_user)
        if current_user.role not in {UserRole.admin, UserRole.agent} and not visible:
            continue
        scoped.append(_to_out(record, user=current_user))
    return scoped


@router.get("/problems/{problem_id}", response_model=ProblemDetailOut)
def get_problem_by_id(
    problem_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProblemDetailOut:
    problem = get_problem(db, problem_id)
    if not problem:
        raise NotFoundError("problem_not_found", details={"problem_id": problem_id})
    detail = _to_detail(problem, user=current_user)
    if current_user.role not in {UserRole.admin, UserRole.agent} and not detail.tickets:
        raise NotFoundError("problem_not_found", details={"problem_id": problem_id})
    return detail


@router.get("/problems/{problem_id}/ai-suggestions", response_model=ProblemAISuggestionsOut)
def get_problem_ai_suggestions(
    problem_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProblemAISuggestionsOut:
    problem = get_problem(db, problem_id)
    if not problem:
        raise NotFoundError("problem_not_found", details={"problem_id": problem_id})
    visible = _visible_tickets(problem, user=current_user)
    if current_user.role not in {UserRole.admin, UserRole.agent} and not visible:
        raise NotFoundError("problem_not_found", details={"problem_id": problem_id})
    payload = build_problem_ai_suggestions(db, problem, tickets=visible)
    return ProblemAISuggestionsOut(
        problem_id=problem.id,
        category=problem.category,
        assignee=payload.get("assignee"),
        suggestions=[str(item) for item in payload.get("suggestions", []) if str(item).strip()],
        suggestions_scored=[
            ProblemAISuggestionItem(
                text=str(item.get("text", "")).strip(),
                confidence=int(item.get("confidence", 0)),
            )
            for item in payload.get("suggestions_scored", [])
            if str(item.get("text", "")).strip()
        ],
        root_cause_suggestion=(
            str(payload.get("root_cause_suggestion")).strip()
            if payload.get("root_cause_suggestion")
            else None
        ),
        workaround_suggestion=(
            str(payload.get("workaround_suggestion")).strip()
            if payload.get("workaround_suggestion")
            else None
        ),
        permanent_fix_suggestion=(
            str(payload.get("permanent_fix_suggestion")).strip()
            if payload.get("permanent_fix_suggestion")
            else None
        ),
        root_cause_confidence=(
            int(payload.get("root_cause_confidence"))
            if payload.get("root_cause_confidence") is not None
            else None
        ),
        workaround_confidence=(
            int(payload.get("workaround_confidence"))
            if payload.get("workaround_confidence") is not None
            else None
        ),
        permanent_fix_confidence=(
            int(payload.get("permanent_fix_confidence"))
            if payload.get("permanent_fix_confidence") is not None
            else None
        ),
    )


@router.post("/problems/detect", response_model=ProblemDetectResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.agent))])
def run_problem_detection(
    payload: ProblemDetectRequest = Body(default=ProblemDetectRequest()),
    db: Session = Depends(get_db),
) -> ProblemDetectResponse:
    result = detect_problems(db, window_days=payload.window_days, min_count=payload.min_count)
    return ProblemDetectResponse(**result)


@router.patch("/problems/{problem_id}", response_model=ProblemOut, dependencies=[Depends(require_roles(UserRole.admin, UserRole.agent))])
def patch_problem(
    payload: ProblemUpdate,
    problem_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProblemOut:
    problem = get_problem(db, problem_id)
    if not problem:
        raise NotFoundError("problem_not_found", details={"problem_id": problem_id})
    try:
        updated = update_problem(db, problem, payload)
    except ValueError as exc:
        raise BadRequestError(str(exc))
    return _to_out(updated, user=current_user)


@router.post(
    "/problems/{problem_id}/assignee",
    response_model=ProblemAssigneeUpdateResponse,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.agent))],
)
def patch_problem_assignee(
    payload: ProblemAssigneeUpdateRequest,
    problem_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
) -> ProblemAssigneeUpdateResponse:
    problem = get_problem(db, problem_id)
    if not problem:
        raise NotFoundError("problem_not_found", details={"problem_id": problem_id})
    try:
        assignee, updated_tickets = assign_problem_assignee(
            db,
            problem,
            mode=payload.mode,
            assignee=payload.assignee,
        )
    except ValueError as exc:
        raise BadRequestError(str(exc))
    return ProblemAssigneeUpdateResponse(
        problem_id=problem.id,
        assignee=assignee,
        updated_tickets=updated_tickets,
        mode=payload.mode,
    )


@router.post("/problems/{problem_id}/link/{ticket_id}", response_model=ProblemLinkResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.agent))])
def link_ticket_to_problem(
    problem_id: str = Path(..., min_length=3, max_length=32),
    ticket_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
) -> ProblemLinkResponse:
    problem = get_problem(db, problem_id)
    if not problem:
        raise NotFoundError("problem_not_found", details={"problem_id": problem_id})
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})
    linked = link_ticket(db, problem, ticket)
    return ProblemLinkResponse(problem_id=problem.id, ticket_id=ticket.id, linked=linked)


@router.post("/problems/{problem_id}/unlink/{ticket_id}", response_model=ProblemLinkResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.agent))])
def unlink_ticket_from_problem(
    problem_id: str = Path(..., min_length=3, max_length=32),
    ticket_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
) -> ProblemLinkResponse:
    problem = get_problem(db, problem_id)
    if not problem:
        raise NotFoundError("problem_not_found", details={"problem_id": problem_id})
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})
    linked = unlink_ticket(db, problem, ticket)
    return ProblemLinkResponse(problem_id=problem.id, ticket_id=ticket.id, linked=linked)


@router.post(
    "/problems/{problem_id}/resolve-linked-tickets",
    response_model=ResolveLinkedTicketsResponse,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.agent))],
)
def resolve_problem_linked_tickets(
    payload: ResolveLinkedTicketsRequest,
    problem_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ResolveLinkedTicketsResponse:
    if not payload.confirm:
        raise BadRequestError("confirmation_required")
    problem = get_problem(db, problem_id)
    if not problem:
        raise NotFoundError("problem_not_found", details={"problem_id": problem_id})
    resolved_count = resolve_linked_tickets(
        db,
        problem,
        actor=current_user.name,
        resolution_comment=payload.resolution_comment,
    )
    return ResolveLinkedTicketsResponse(problem_id=problem.id, resolved_count=resolved_count)
