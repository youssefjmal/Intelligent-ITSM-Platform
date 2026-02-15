"""Service helpers for ticket CRUD and analytics."""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections import Counter
from typing import Literal
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.rbac import can_view_ticket, filter_tickets_for_user
from app.integrations.jira.mapper import JIRA_SOURCE
from app.integrations.jira.outbound import create_jira_issue_for_ticket
from app.models.ticket import Ticket, TicketComment
from app.models.user import User
from app.models.enums import SeniorityLevel, TicketCategory, TicketPriority, TicketStatus, UserRole
from app.schemas.ticket import TicketCreate, TicketTriageUpdate

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {TicketStatus.open, TicketStatus.in_progress, TicketStatus.pending}
RESOLVED_STATUSES = {TicketStatus.resolved, TicketStatus.closed}
PROBLEM_REPEAT_THRESHOLD = 3
PROBLEM_TRIGGER_WINDOW_DAYS = 7
PROBLEM_TRIGGER_COUNT_WINDOW = 5
PROBLEM_TRIGGER_COUNT_DAY = 4
MODEL_VERSION_MAX_LEN = 40

SIGNATURE_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "les",
    "des",
    "pour",
    "avec",
    "dans",
    "une",
    "sur",
    "ticket",
    "incident",
    "issue",
}

CATEGORY_ROUTING = {
    TicketCategory.infrastructure: {
        "method": "balanced",
        "specializations": {"server_maintenance", "cloud", "virtualization"},
    },
    TicketCategory.network: {
        "method": "balanced",
        "specializations": {"routers", "switches", "vpn", "wifi", "firewalls"},
    },
    TicketCategory.security: {
        "method": "direct",
        "specializations": {"threat_detection", "access_management", "compliance"},
    },
    TicketCategory.application: {
        "method": "round_robin",
        "specializations": {"software_bugs", "database_issues", "internal_tools"},
    },
    TicketCategory.service_request: {
        "method": "balanced",
        "specializations": {"onboarding", "software_installs", "permissions"},
    },
    TicketCategory.hardware: {
        "method": "balanced",
        "specializations": {"laptops", "printers", "peripherals"},
    },
    TicketCategory.email: {
        "method": "round_robin",
        "specializations": {"mailbox_issues", "distribution_lists", "outlook_workspace"},
    },
    TicketCategory.problem: {
        "method": "direct",
        "specializations": set(),
    },
}


def _normalize_specializations(specializations: list[str] | None) -> set[str]:
    return {str(item).strip().lower() for item in (specializations or []) if str(item).strip()}


def _seniority_rank(level: SeniorityLevel | None) -> int:
    return {
        SeniorityLevel.intern: 0,
        SeniorityLevel.junior: 1,
        SeniorityLevel.middle: 2,
        SeniorityLevel.senior: 3,
    }.get(level, 0)


def _active_ticket_counts(db: Session) -> dict[str, int]:
    rows = (
        db.query(Ticket.assignee, func.count(Ticket.id))
        .filter(Ticket.status.in_(ACTIVE_STATUSES))
        .group_by(Ticket.assignee)
        .all()
    )
    return {assignee: count for assignee, count in rows if assignee}


def _filter_candidates_by_specs(users: list[User], specs: set[str]) -> list[User]:
    if not specs:
        return users
    return [
        u
        for u in users
        if _normalize_specializations(u.specializations).intersection(specs)
    ]


def _apply_availability_and_capacity(candidates: list[User], load_map: dict[str, int]) -> list[User]:
    available = [u for u in candidates if u.is_available]
    if available:
        candidates = available

    under_capacity = [
        u
        for u in candidates
        if load_map.get(u.name, 0) < max(1, u.max_concurrent_tickets or 1)
    ]
    return under_capacity or candidates


def _balanced_workload(candidates: list[User], load_map: dict[str, int]) -> User | None:
    if not candidates:
        return None
    def sort_key(user: User) -> tuple:
        max_tickets = max(1, user.max_concurrent_tickets or 1)
        load = load_map.get(user.name, 0)
        load_ratio = load / max_tickets
        return (load_ratio, load, user.name.lower())
    return sorted(candidates, key=sort_key)[0]


def _round_robin(db: Session, candidates: list[User], category: TicketCategory) -> User | None:
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda u: u.name.lower())
    names = [u.name for u in ordered]
    last = (
        db.query(Ticket)
        .filter(Ticket.category == category, Ticket.assignee.in_(names))
        .order_by(Ticket.created_at.desc())
        .first()
    )
    if not last or last.assignee not in names:
        return ordered[0]
    idx = (names.index(last.assignee) + 1) % len(names)
    return ordered[idx]


def _direct_assignment(candidates: list[User], load_map: dict[str, int]) -> User | None:
    if not candidates:
        return None

    def sort_key(user: User) -> tuple:
        max_tickets = max(1, user.max_concurrent_tickets or 1)
        load = load_map.get(user.name, 0)
        return (-_seniority_rank(user.seniority_level), load, user.name.lower())

    return sorted(candidates, key=sort_key)[0]


def select_best_assignee(
    db: Session,
    *,
    category: TicketCategory,
    priority: TicketPriority,
) -> str | None:
    agents = (
        db.query(User)
        .filter(User.role.in_([UserRole.admin, UserRole.agent]))
        .order_by(User.name.asc())
        .all()
    )
    if not agents:
        return None

    routing = CATEGORY_ROUTING.get(category)
    specs = set()
    method = "balanced"
    if routing:
        specs = set(routing.get("specializations") or [])
        method = str(routing.get("method") or "balanced")

    load_map = _active_ticket_counts(db)
    candidates = _apply_availability_and_capacity(agents, load_map)
    filtered = _filter_candidates_by_specs(candidates, specs)
    if filtered:
        candidates = filtered

    if method == "round_robin":
        chosen = _round_robin(db, candidates, category)
    elif method == "direct":
        chosen = _direct_assignment(candidates, load_map)
    else:
        chosen = _balanced_workload(candidates, load_map)

    return chosen.name if chosen else None


def list_tickets(db: Session) -> list[Ticket]:
    return db.query(Ticket).order_by(Ticket.created_at.desc()).all()


def list_tickets_for_user(db: Session, user: User) -> list[Ticket]:
    return filter_tickets_for_user(user, list_tickets(db))


def get_ticket(db: Session, ticket_id: str) -> Ticket | None:
    return db.get(Ticket, ticket_id)


def get_ticket_for_user(db: Session, ticket_id: str, user: User) -> Ticket | None:
    ticket = get_ticket(db, ticket_id)
    if not ticket:
        return None
    if not can_view_ticket(user, ticket):
        return None
    return ticket


def _next_ticket_id(db: Session) -> str:
    ids = [t[0] for t in db.query(Ticket.id).all()]
    max_num = 1000
    for tid in ids:
        try:
            num = int(tid.split("-")[-1])
            max_num = max(max_num, num)
        except ValueError:
            continue
    return f"TW-{max_num + 1}"


def _next_comment_id(db: Session) -> str:
    ids = [row[0] for row in db.query(TicketComment.id).all()]
    max_num = 0
    for cid in ids:
        match = re.search(r"(\d+)$", cid or "")
        if not match:
            continue
        max_num = max(max_num, int(match.group(1)))
    return f"c{max_num + 1}"


def _normalize_model_version(value: str | None, *, default: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        cleaned = default
    return cleaned[:MODEL_VERSION_MAX_LEN]


def _signature_tokens(text: str | None) -> set[str]:
    normalized = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    tokens = [
        token
        for token in normalized.split()
        if len(token) > 2 and token not in SIGNATURE_STOPWORDS
    ]
    return set(tokens[:12])


def _signature_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    common = len(left.intersection(right))
    return common / max(1, min(len(left), len(right)))


def _incident_signature(ticket: Ticket) -> set[str]:
    return _signature_tokens(f"{ticket.title} {ticket.description}")


def _comment_signature(comment: str | None) -> set[str]:
    return _signature_tokens(comment or "")


def _cluster_temporal_counts(cluster: list[Ticket], *, now: dt.datetime) -> tuple[int, int, str | None]:
    recent_cutoff = now - dt.timedelta(days=PROBLEM_TRIGGER_WINDOW_DAYS)
    recent_occurrences_7d = sum(1 for item in cluster if analytics_created_at(item) >= recent_cutoff)

    day_counts: Counter[str] = Counter()
    for item in cluster:
        day_key = analytics_created_at(item).date().isoformat()
        day_counts[day_key] += 1

    if not day_counts:
        return recent_occurrences_7d, 0, None
    same_day_peak_date, same_day_peak = day_counts.most_common(1)[0]
    return recent_occurrences_7d, same_day_peak, same_day_peak_date


def _problem_trigger_reasons(recent_occurrences_7d: int, same_day_peak: int) -> list[str]:
    reasons: list[str] = []
    if recent_occurrences_7d >= PROBLEM_TRIGGER_COUNT_WINDOW:
        reasons.append("5_in_7_days")
    if same_day_peak >= PROBLEM_TRIGGER_COUNT_DAY:
        reasons.append("4_same_day")
    return reasons


def _fallback_problem_recommendation(category: TicketCategory) -> str:
    mapping = {
        TicketCategory.infrastructure: "Verifier saturation CPU/RAM/disque, stabiliser le service, puis planifier un correctif permanent.",
        TicketCategory.network: "Auditer routeurs/switch/vpn, isoler l'equipement fautif et appliquer un plan de correction reseau.",
        TicketCategory.security: "Lancer un controle IAM/logs, corriger les acces anormaux et renforcer la politique de securite.",
        TicketCategory.application: "Analyser stack trace et logs applicatifs, corriger le bug racine puis deployer un patch teste.",
        TicketCategory.service_request: "Standardiser la demande en runbook (validation, acces, checklist) pour reduire les erreurs repetitives.",
        TicketCategory.hardware: "Verifier etat materiel/firmware, remplacer la piece defaillante puis mettre a jour la base d'actifs.",
        TicketCategory.email: "Controler quotas/routage/boites partagees, corriger la configuration et documenter les bonnes pratiques.",
        TicketCategory.problem: "Faire une RCA formelle, definir actions preventives et suivre un plan de reduction de recurrence.",
    }
    return mapping.get(category, "Executer une RCA, standardiser le correctif et suivre la recurrence chaque semaine.")


def _resolution_recommendation_snippet(resolution: str | None) -> str | None:
    text = (resolution or "").strip()
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[\.\!\?;])\s+", normalized)
    head = (parts[0] if parts else normalized).strip()
    if not head:
        return None
    words = head.split()
    if len(words) > 18:
        head = " ".join(words[:18]).rstrip(",:;") + "..."
    return head


def _build_problem_ai_recommendation(cluster: list[Ticket]) -> tuple[str, int]:
    snippets: list[str] = []
    for item in cluster:
        if item.status not in {TicketStatus.resolved, TicketStatus.closed}:
            continue
        snippet = _resolution_recommendation_snippet(item.resolution)
        if snippet:
            snippets.append(snippet)

    if snippets:
        counts = Counter(snippets)
        chosen = counts.most_common(1)[0][0]
        return f"Recommendation IA: reproduire en priorite cette action qui a deja fonctionne: {chosen}", 84

    dominant_category = Counter(t.category for t in cluster).most_common(1)[0][0]
    return f"Recommendation IA: {_fallback_problem_recommendation(dominant_category)}", 68


def _should_promote_to_problem(db: Session, ticket: Ticket, resolution_comment: str) -> bool:
    if ticket.category == TicketCategory.problem:
        return False

    others = db.query(Ticket).filter(Ticket.id != ticket.id).all()
    if not others:
        return False
    resolved_only = [item for item in others if item.status in {TicketStatus.resolved, TicketStatus.closed}]

    incident_matches = 1
    comment_matches = 1
    this_incident = _incident_signature(ticket)
    this_comment = _comment_signature(resolution_comment)
    now = dt.datetime.now(dt.timezone.utc)
    recent_cutoff = now - dt.timedelta(days=PROBLEM_TRIGGER_WINDOW_DAYS)
    created_at = analytics_created_at(ticket)
    recent_incident_matches = 1 if created_at >= recent_cutoff else 0
    same_day_incident_matches = 1
    same_day = created_at.date()

    for existing in others:
        overlap = _signature_overlap(this_incident, _incident_signature(existing))
        if overlap >= 0.6:
            incident_matches += 1
            existing_created = analytics_created_at(existing)
            if existing_created >= recent_cutoff:
                recent_incident_matches += 1
            if existing_created.date() == same_day:
                same_day_incident_matches += 1
    for existing in resolved_only:
        if _signature_overlap(this_comment, _comment_signature(existing.resolution or "")) >= 0.8:
            comment_matches += 1

    return (
        incident_matches >= PROBLEM_REPEAT_THRESHOLD
        or comment_matches >= PROBLEM_REPEAT_THRESHOLD
        or recent_incident_matches >= PROBLEM_TRIGGER_COUNT_WINDOW
        or same_day_incident_matches >= PROBLEM_TRIGGER_COUNT_DAY
    )


def create_ticket(db: Session, data: TicketCreate, *, reporter_id: str | None = None) -> Ticket:
    from app.services.problems import link_ticket_to_problem
    from app.services.ai import classify_ticket

    now = dt.datetime.now(dt.timezone.utc)
    auto_assignment_applied = False
    assignee = (data.assignee or "").strip()
    if not assignee or assignee.lower() in {"auto", "auto-assign", "auto_assign"}:
        assignee = select_best_assignee(db, category=data.category, priority=data.priority) or ""
        auto_assignment_applied = bool(assignee)
    if not assignee:
        assignee = data.reporter or "Unassigned"

    predicted_priority = data.predicted_priority
    predicted_category = data.predicted_category
    if predicted_priority is None or predicted_category is None:
        try:
            ai_priority, ai_category, _recommendations = classify_ticket(data.title, data.description)
            if predicted_priority is None:
                predicted_priority = ai_priority
            if predicted_category is None:
                predicted_category = ai_category
        except Exception:  # noqa: BLE001
            pass

    auto_priority_applied = bool(
        data.auto_priority_applied
        or (
            predicted_priority is not None
            and predicted_category is not None
            and predicted_priority == data.priority
            and predicted_category == data.category
        )
    )
    assignment_model_version = _normalize_model_version(
        data.assignment_model_version,
        default="smart-v1" if auto_assignment_applied else "manual",
    )
    priority_model_version = _normalize_model_version(
        data.priority_model_version,
        default="smart-v1" if auto_priority_applied else "manual",
    )

    ticket = Ticket(
        id=_next_ticket_id(db),
        title=data.title,
        description=data.description,
        priority=data.priority,
        category=data.category,
        assignee=assignee,
        reporter=data.reporter,
        reporter_id=reporter_id,
        auto_assignment_applied=auto_assignment_applied,
        auto_priority_applied=auto_priority_applied,
        assignment_model_version=assignment_model_version,
        priority_model_version=priority_model_version,
        predicted_priority=predicted_priority,
        predicted_category=predicted_category,
        assignment_change_count=0,
        first_action_at=None,
        resolved_at=None,
        status=TicketStatus.open,
        created_at=now,
        updated_at=now,
        tags=data.tags,
        comments=[],
    )
    db.add(ticket)
    db.flush()
    link_ticket_to_problem(db, ticket)
    db.commit()
    db.refresh(ticket)

    # Best-effort outbound sync: local creation succeeds even if Jira push fails.
    if not ticket.external_id:
        jira_key = create_jira_issue_for_ticket(ticket)
        if jira_key:
            now = dt.datetime.now(dt.timezone.utc)
            ticket.jira_key = jira_key
            ticket.external_source = JIRA_SOURCE
            ticket.external_id = jira_key
            ticket.external_updated_at = now
            ticket.last_synced_at = now
            db.add(ticket)
            db.commit()
            db.refresh(ticket)
            logger.info("Ticket pushed to Jira: %s -> %s", ticket.id, jira_key)

    logger.info("Ticket created: %s", ticket.id)
    return ticket


def update_status(
    db: Session,
    ticket_id: str,
    status: TicketStatus,
    *,
    actor: str,
    resolution_comment: str | None = None,
) -> Ticket | None:
    from app.services.problems import link_ticket_to_problem

    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        logger.warning("Ticket status update failed (not found): %s", ticket_id)
        return None
    now = dt.datetime.now(dt.timezone.utc)
    normalized_comment = (resolution_comment or "").strip()
    has_resolution = bool((ticket.resolution or "").strip())

    if status == TicketStatus.resolved and not normalized_comment:
        raise ValueError("resolution_comment_required")
    if status == TicketStatus.closed and not normalized_comment and not has_resolution:
        raise ValueError("resolution_comment_required")

    if normalized_comment:
        comment = TicketComment(
            id=_next_comment_id(db),
            ticket_id=ticket.id,
            author=(actor or "").strip() or ticket.assignee or "System",
            content=normalized_comment,
            created_at=now,
        )
        db.add(comment)
        ticket.resolution = normalized_comment

    promotion_source = normalized_comment or (ticket.resolution or "")
    if status in {TicketStatus.resolved, TicketStatus.closed} and promotion_source:
        if _should_promote_to_problem(db, ticket, promotion_source):
            ticket.category = TicketCategory.problem
            tags = list(ticket.tags or [])
            if "problem" not in tags:
                tags.append("problem")
            if "root-cause-analysis" not in tags:
                tags.append("root-cause-analysis")
            ticket.tags = tags

    ticket.status = status
    if ticket.first_action_at is None and status != TicketStatus.open:
        ticket.first_action_at = now
    if status in RESOLVED_STATUSES:
        ticket.resolved_at = now
    elif ticket.resolved_at is not None:
        ticket.resolved_at = None
    ticket.updated_at = now
    db.add(ticket)
    db.flush()
    link_ticket_to_problem(db, ticket)
    db.commit()
    db.refresh(ticket)
    logger.info("Ticket status updated: %s -> %s", ticket.id, status.value)
    return ticket


def update_ticket_triage(
    db: Session,
    ticket_id: str,
    payload: TicketTriageUpdate,
    *,
    actor: str,
) -> Ticket | None:
    from app.services.problems import link_ticket_to_problem

    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        logger.warning("Ticket triage update failed (not found): %s", ticket_id)
        return None

    now = dt.datetime.now(dt.timezone.utc)
    has_changes = False

    if payload.assignee and payload.assignee != ticket.assignee:
        ticket.assignee = payload.assignee
        ticket.assignment_change_count = int(ticket.assignment_change_count or 0) + 1
        has_changes = True

    if payload.priority and payload.priority != ticket.priority:
        ticket.priority = payload.priority
        has_changes = True

    if payload.category and payload.category != ticket.category:
        ticket.category = payload.category
        has_changes = True

    note = (payload.comment or "").strip()
    if note:
        comment = TicketComment(
            id=_next_comment_id(db),
            ticket_id=ticket.id,
            author=(actor or "").strip() or ticket.assignee or "System",
            content=note,
            created_at=now,
        )
        db.add(comment)
        has_changes = True

    if not has_changes:
        return ticket

    if ticket.first_action_at is None:
        ticket.first_action_at = now
    ticket.updated_at = now
    db.add(ticket)
    db.flush()
    link_ticket_to_problem(db, ticket)
    db.commit()
    db.refresh(ticket)
    logger.info("Ticket triage updated: %s", ticket.id)
    return ticket


def compute_stats(tickets: list[Ticket]) -> dict:
    total = len(tickets)
    open_count = sum(1 for t in tickets if t.status == TicketStatus.open)
    in_progress = sum(1 for t in tickets if t.status == TicketStatus.in_progress)
    pending = sum(1 for t in tickets if t.status == TicketStatus.pending)
    resolved = sum(1 for t in tickets if t.status == TicketStatus.resolved)
    closed = sum(1 for t in tickets if t.status == TicketStatus.closed)
    critical = sum(1 for t in tickets if t.priority == TicketPriority.critical)
    high = sum(1 for t in tickets if t.priority == TicketPriority.high)

    resolved_tickets = [t for t in tickets if t.status in RESOLVED_STATUSES]
    if resolved_tickets:
        days = []
        for ticket in resolved_tickets:
            created = analytics_created_at(ticket)
            resolved_at = analytics_resolved_at(ticket) or analytics_updated_at(ticket)
            days.append(max((resolved_at - created).total_seconds() / 86400, 0))
        avg_resolution = round(sum(days) / len(days), 2)
    else:
        avg_resolution = 0.0

    resolution_rate = round(((resolved + closed) / total) * 100) if total else 0

    return {
        "total": total,
        "open": open_count,
        "in_progress": in_progress,
        "pending": pending,
        "resolved": resolved,
        "closed": closed,
        "critical": critical,
        "high": high,
        "resolution_rate": resolution_rate,
        "avg_resolution_days": avg_resolution,
    }


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _duration_hours(start: dt.datetime, end: dt.datetime) -> float:
    return max((_to_utc(end) - _to_utc(start)).total_seconds() / 3600, 0.0)


def _is_ia_ticket(ticket: Ticket) -> bool:
    return bool(ticket.auto_assignment_applied or ticket.auto_priority_applied)


def _filter_performance_tickets(
    tickets: list[Ticket],
    *,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    category: TicketCategory | None = None,
    assignee: str | None = None,
    scope: Literal["all", "before", "after"] = "all",
) -> list[Ticket]:
    start_dt: dt.datetime | None = None
    end_dt: dt.datetime | None = None
    if date_from:
        start_dt = dt.datetime.combine(date_from, dt.time.min).replace(tzinfo=dt.timezone.utc)
    if date_to:
        end_dt = dt.datetime.combine(date_to, dt.time.max).replace(tzinfo=dt.timezone.utc)

    assignee_filter = (assignee or "").strip().lower()
    filtered: list[Ticket] = []
    for ticket in tickets:
        created = analytics_created_at(ticket)
        if start_dt and created < start_dt:
            continue
        if end_dt and created > end_dt:
            continue
        if category and ticket.category != category:
            continue
        if assignee_filter and (ticket.assignee or "").strip().lower() != assignee_filter:
            continue
        if scope == "before" and _is_ia_ticket(ticket):
            continue
        if scope == "after" and not _is_ia_ticket(ticket):
            continue
        filtered.append(ticket)
    return filtered


def compute_assignment_performance(
    tickets: list[Ticket],
    *,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    category: TicketCategory | None = None,
    assignee: str | None = None,
    scope: Literal["all", "before", "after"] = "all",
) -> dict:
    tickets = _filter_performance_tickets(
        tickets,
        date_from=date_from,
        date_to=date_to,
        category=category,
        assignee=assignee,
        scope=scope,
    )
    total = len(tickets)
    resolved_tickets = [t for t in tickets if t.status in RESOLVED_STATUSES]

    before_group = [t for t in resolved_tickets if not _is_ia_ticket(t)]
    after_group = [t for t in resolved_tickets if _is_ia_ticket(t)]

    mttr_before = _avg(
        [
            _duration_hours(analytics_created_at(t), analytics_resolved_at(t) or analytics_updated_at(t))
            for t in before_group
        ]
    )
    mttr_after = _avg(
        [
            _duration_hours(analytics_created_at(t), analytics_resolved_at(t) or analytics_updated_at(t))
            for t in after_group
        ]
    )

    reassigned_tickets = sum(1 for t in tickets if int(t.assignment_change_count or 0) > 0)
    reassignment_rate = round((reassigned_tickets / total) * 100, 2) if total else 0.0

    first_action_values: list[float] = []
    for ticket in tickets:
        first_action = analytics_first_action_at(ticket)
        if first_action is None:
            continue
        first_action_values.append(_duration_hours(analytics_created_at(ticket), first_action))
    avg_first_action = _avg(first_action_values)

    auto_assigned = [t for t in tickets if _is_ia_ticket(t)]
    auto_assign_samples = len(auto_assigned)
    auto_assign_correct = sum(1 for t in auto_assigned if int(t.assignment_change_count or 0) == 0)
    auto_assign_accuracy = (
        round((auto_assign_correct / auto_assign_samples) * 100, 2)
        if auto_assign_samples
        else None
    )

    classified = [
        t
        for t in tickets
        if t.predicted_priority is not None or t.predicted_category is not None
    ]
    classification_samples = len(classified)
    classification_correct = 0
    for ticket in classified:
        checks = 0
        matches = 0
        if ticket.predicted_priority is not None:
            checks += 1
            if ticket.predicted_priority == ticket.priority:
                matches += 1
        if ticket.predicted_category is not None:
            checks += 1
            if ticket.predicted_category == ticket.category:
                matches += 1
        if checks > 0 and checks == matches:
            classification_correct += 1

    classification_accuracy = (
        round((classification_correct / classification_samples) * 100, 2)
        if classification_samples
        else None
    )

    return {
        "total_tickets": total,
        "resolved_tickets": len(resolved_tickets),
        "mttr_hours": {
            "before": mttr_before,
            "after": mttr_after,
        },
        "reassignment_rate": reassignment_rate,
        "reassigned_tickets": reassigned_tickets,
        "avg_time_to_first_action_hours": avg_first_action,
        "classification_accuracy_rate": classification_accuracy,
        "classification_samples": classification_samples,
        "auto_assignment_accuracy_rate": auto_assign_accuracy,
        "auto_assignment_samples": auto_assign_samples,
    }


def compute_category_breakdown(tickets: list[Ticket]) -> list[dict]:
    categories = [
        TicketCategory.infrastructure,
        TicketCategory.network,
        TicketCategory.security,
        TicketCategory.application,
        TicketCategory.service_request,
        TicketCategory.hardware,
        TicketCategory.email,
        TicketCategory.problem,
    ]
    labels = {
        TicketCategory.infrastructure: "Infrastructure",
        TicketCategory.network: "Reseau",
        TicketCategory.security: "Securite",
        TicketCategory.application: "Application",
        TicketCategory.service_request: "Demande de service",
        TicketCategory.hardware: "Materiel",
        TicketCategory.email: "Email",
        TicketCategory.problem: "Probleme",
    }
    return [
        {"category": labels[c], "count": sum(1 for t in tickets if t.category == c)}
        for c in categories
    ]


def compute_priority_breakdown(tickets: list[Ticket]) -> list[dict]:
    priorities = [
        TicketPriority.critical,
        TicketPriority.high,
        TicketPriority.medium,
        TicketPriority.low,
    ]
    labels = {
        TicketPriority.critical: "Critique",
        TicketPriority.high: "Haute",
        TicketPriority.medium: "Moyenne",
        TicketPriority.low: "Basse",
    }
    colors = {
        TicketPriority.critical: "#dc2626",
        TicketPriority.high: "#f59e0b",
        TicketPriority.medium: "#2e9461",
        TicketPriority.low: "#64748b",
    }
    return [
        {
            "priority": labels[p],
            "count": sum(1 for t in tickets if t.priority == p),
            "fill": colors[p],
        }
        for p in priorities
    ]


def compute_weekly_trends(tickets: list[Ticket], weeks: int = 6) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc)
    buckets = []
    for i in range(weeks):
        start = (now - dt.timedelta(weeks=weeks - i)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + dt.timedelta(weeks=1)
        opened = sum(1 for t in tickets if start <= analytics_created_at(t) < end)
        closed = sum(
            1
            for t in tickets
            if t.status in RESOLVED_STATUSES and start <= (analytics_resolved_at(t) or analytics_updated_at(t)) < end
        )
        pending = sum(1 for t in tickets if t.status == TicketStatus.pending and start <= analytics_updated_at(t) < end)
        buckets.append({"week": f"Sem {i + 1}", "opened": opened, "closed": closed, "pending": pending})
    return buckets


def _to_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def analytics_created_at(ticket: Ticket) -> dt.datetime:
    return _to_utc(ticket.jira_created_at or ticket.created_at)


def analytics_updated_at(ticket: Ticket) -> dt.datetime:
    return _to_utc(ticket.jira_updated_at or ticket.updated_at)


def analytics_resolved_at(ticket: Ticket) -> dt.datetime | None:
    if ticket.resolved_at is not None:
        return _to_utc(ticket.resolved_at)
    if ticket.status in RESOLVED_STATUSES:
        return analytics_updated_at(ticket)
    return None


def analytics_first_action_at(ticket: Ticket) -> dt.datetime | None:
    if ticket.first_action_at is None:
        return None
    return _to_utc(ticket.first_action_at)


def _days_since(value: dt.datetime, *, now: dt.datetime) -> int:
    delta = now - _to_utc(value)
    return max(0, int(delta.total_seconds() // 86400))


def _priority_rank(priority: TicketPriority) -> int:
    order = {
        TicketPriority.critical: 0,
        TicketPriority.high: 1,
        TicketPriority.medium: 2,
        TicketPriority.low: 3,
    }
    return order.get(priority, 99)


def _ticket_insight_payload(ticket: Ticket, *, now: dt.datetime) -> dict:
    created = analytics_created_at(ticket)
    updated = analytics_updated_at(ticket)
    return {
        "id": ticket.id,
        "title": ticket.title,
        "priority": ticket.priority.value,
        "status": ticket.status.value,
        "category": ticket.category.value,
        "assignee": ticket.assignee,
        "created_at": created.isoformat(),
        "updated_at": updated.isoformat(),
        "age_days": _days_since(created, now=now),
        "inactive_days": _days_since(updated, now=now),
    }


def compute_operational_insights(
    tickets: list[Ticket],
    *,
    recent_days: int = 7,
    stale_days: int = 5,
    limit: int = 6,
) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    recent_window_days = max(1, int(recent_days))
    stale_window_days = max(1, int(stale_days))
    top_n = max(1, int(limit))
    recent_cutoff = now - dt.timedelta(days=recent_window_days)
    stale_cutoff = now - dt.timedelta(days=stale_window_days)

    active_tickets = [t for t in tickets if t.status in ACTIVE_STATUSES]

    critical_recent = [
        t
        for t in active_tickets
        if t.priority == TicketPriority.critical and analytics_created_at(t) >= recent_cutoff
    ]
    critical_recent.sort(key=analytics_created_at, reverse=True)

    stale_active = [
        t
        for t in active_tickets
        if analytics_updated_at(t) <= stale_cutoff
    ]
    stale_active.sort(
        key=lambda t: (
            _priority_rank(t.priority),
            -_days_since(analytics_updated_at(t), now=now),
            analytics_updated_at(t),
        )
    )

    critical_recent_rows = [_ticket_insight_payload(ticket, now=now) for ticket in critical_recent[:top_n]]
    stale_active_rows = [_ticket_insight_payload(ticket, now=now) for ticket in stale_active[:top_n]]

    return {
        "critical_recent": critical_recent_rows,
        "stale_active": stale_active_rows,
        "recent_days": recent_window_days,
        "stale_days": stale_window_days,
        "counts": {
            "critical_recent": len(critical_recent_rows),
            "stale_active": len(stale_active_rows),
        },
    }


def compute_problem_insights(tickets: list[Ticket], *, min_repetitions: int = 2, limit: int = 6) -> list[dict]:
    if not tickets:
        return []

    now = dt.datetime.now(dt.timezone.utc)
    insights: list[dict] = []

    def _cluster_to_payload(cluster: list[Ticket], *, problem_id: str | None) -> dict:
        cluster_sorted = sorted(cluster, key=analytics_updated_at, reverse=True)
        active_count = sum(1 for t in cluster if t.status in ACTIVE_STATUSES)
        problem_count = 1 if problem_id else sum(1 for t in cluster if t.category == TicketCategory.problem)
        highest_priority = "low"
        if any(t.priority == TicketPriority.critical for t in cluster):
            highest_priority = "critical"
        elif any(t.priority == TicketPriority.high for t in cluster):
            highest_priority = "high"
        elif any(t.priority == TicketPriority.medium for t in cluster):
            highest_priority = "medium"

        recent_occurrences_7d, same_day_peak, same_day_peak_date = _cluster_temporal_counts(cluster_sorted, now=now)
        trigger_reasons = _problem_trigger_reasons(recent_occurrences_7d, same_day_peak)
        problem_triggered = bool(trigger_reasons)
        ai_recommendation, ai_recommendation_confidence = _build_problem_ai_recommendation(cluster_sorted)

        return {
            "problem_id": problem_id,
            "title": cluster_sorted[0].title,
            "occurrences": len(cluster_sorted),
            "active_count": active_count,
            "problem_count": problem_count,
            "highest_priority": highest_priority,
            "latest_ticket_id": cluster_sorted[0].id,
            "latest_updated_at": analytics_updated_at(cluster_sorted[0]).isoformat(),
            "ticket_ids": [t.id for t in cluster_sorted[:5]],
            "problem_triggered": problem_triggered,
            "trigger_reasons": trigger_reasons,
            "recent_occurrences_7d": recent_occurrences_7d,
            "same_day_peak": same_day_peak,
            "same_day_peak_date": same_day_peak_date,
            "ai_recommendation": ai_recommendation,
            "ai_recommendation_confidence": ai_recommendation_confidence,
        }

    linked_groups: dict[str, list[Ticket]] = {}
    unlinked: list[Ticket] = []
    for ticket in tickets:
        if ticket.problem_id:
            linked_groups.setdefault(ticket.problem_id, []).append(ticket)
        else:
            unlinked.append(ticket)

    for problem_id, cluster in linked_groups.items():
        if len(cluster) < min_repetitions:
            continue
        insights.append(_cluster_to_payload(cluster, problem_id=problem_id))

    sorted_tickets = sorted(unlinked, key=analytics_updated_at, reverse=True)
    signatures = {t.id: _incident_signature(t) for t in sorted_tickets}
    visited: set[str] = set()

    for ticket in sorted_tickets:
        if ticket.id in visited:
            continue

        seed_sig = signatures.get(ticket.id, set())
        cluster: list[Ticket] = [ticket]
        visited.add(ticket.id)
        for other in sorted_tickets:
            if other.id in visited:
                continue
            other_sig = signatures.get(other.id, set())
            if _signature_overlap(seed_sig, other_sig) >= 0.6:
                cluster.append(other)
                visited.add(other.id)

        if len(cluster) < min_repetitions:
            continue
        insights.append(_cluster_to_payload(cluster, problem_id=None))

    priority_weight = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    insights.sort(
        key=lambda item: (
            int(bool(item.get("problem_triggered"))),
            item["problem_count"],
            priority_weight.get(item["highest_priority"], 0),
            item["occurrences"],
            item["active_count"],
        ),
        reverse=True,
    )
    return insights[:limit]
