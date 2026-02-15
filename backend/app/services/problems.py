"""Problem management services for recurring incident detection."""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections import Counter, defaultdict
import unicodedata
from uuid import uuid4

from sqlalchemy.orm import Session, joinedload

from app.models.enums import ProblemStatus, RecommendationImpact, RecommendationType, TicketCategory, TicketPriority, TicketStatus
from app.models.problem import Problem
from app.models.recommendation import Recommendation
from app.models.ticket import Ticket
from app.schemas.problem import ProblemUpdate
from app.services.ai import classify_ticket, score_recommendations
from app.services.tickets import select_best_assignee, update_status
from app.services.users import list_assignees

logger = logging.getLogger(__name__)

ACTIVE_TICKET_STATUSES = {TicketStatus.open, TicketStatus.in_progress, TicketStatus.pending}
PROBLEM_TRIGGER_WINDOW_DAYS = 3
PROBLEM_TRIGGER_MIN_COUNT = 5
PROBLEM_MATCH_SCORE_THRESHOLD = 0.45
SIMILARITY_TICKET_ID_RE = re.compile(r"\b[a-z]{1,12}-\d+\b", re.IGNORECASE)
SIMILARITY_NOISE_TAG_PREFIXES = (
    "local_",
    "priority_",
    "category_",
    "source_",
    "twseed_",
    "jsm_",
)
SIMILARITY_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
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
    "probleme",
    "issue",
}
GENERIC_SIMILARITY_TAGS = {
    "infra",
    "infrastructure",
    "network",
    "reseau",
    "security",
    "securite",
    "application",
    "service",
    "service_request",
    "request",
    "hardware",
    "email",
    "mail",
    "ticket",
    "incident",
    "probleme",
    "problem",
    "support",
    "it",
}
ROOT_CAUSE_HINTS: dict[TicketCategory, str] = {
    TicketCategory.infrastructure: "Correlate this recurrence with infrastructure saturation, failing dependencies, and deployment timeline.",
    TicketCategory.network: "Likely unstable network path or VPN gateway/session handling issue. Validate gateway logs and auth timeouts.",
    TicketCategory.security: "Likely policy or identity mismatch. Verify recent IAM/policy changes and denied access audit events.",
    TicketCategory.application: "Likely application defect triggered by a repeated scenario. Confirm with stack traces and error fingerprints.",
    TicketCategory.service_request: "Likely process/runbook gap causing repetitive manual handling failures.",
    TicketCategory.hardware: "Likely recurring hardware failure or firmware mismatch. Confirm diagnostics and component health.",
    TicketCategory.email: "Likely SMTP routing or mailbox configuration instability. Check queue/backoff and rejection logs.",
    TicketCategory.problem: "Confirm a single dominant root cause across linked incidents before closing.",
}
WORKAROUND_HINTS: dict[TicketCategory, str] = {
    TicketCategory.infrastructure: "Scale up affected resources and restart impacted service instances to stabilize users temporarily.",
    TicketCategory.network: "Restart VPN gateway, clear stale sessions, and reroute impacted users through backup path.",
    TicketCategory.security: "Apply temporary controlled access override for impacted users while audit checks run.",
    TicketCategory.application: "Rollback to the last stable release or disable the failing feature flag as temporary mitigation.",
    TicketCategory.service_request: "Use a temporary manual checklist with explicit validation to avoid repeat errors.",
    TicketCategory.hardware: "Switch to spare device/component and isolate failing hardware from production usage.",
    TicketCategory.email: "Retry queue flush with temporary relay and monitor bounce/retry rates.",
    TicketCategory.problem: "Apply temporary containment while RCA and permanent corrective action are being finalized.",
}
PERMANENT_FIX_HINTS: dict[TicketCategory, str] = {
    TicketCategory.infrastructure: "Automate capacity safeguards, add saturation alerts, and apply durable configuration hardening.",
    TicketCategory.network: "Apply durable network/VPN configuration fix and enforce monitoring for session drops and auth latency.",
    TicketCategory.security: "Harden IAM/policy baseline and add preventive controls for the detected access pattern.",
    TicketCategory.application: "Implement code-level fix, add regression tests, and monitor error-rate rollback guardrails.",
    TicketCategory.service_request: "Standardize the workflow with approvals, templates, and SLA checkpoints.",
    TicketCategory.hardware: "Replace defective assets, update firmware baseline, and track lifecycle health proactively.",
    TicketCategory.email: "Fix SMTP/auth configuration permanently and add proactive delivery/queue alerting.",
    TicketCategory.problem: "Document RCA actions as a permanent runbook and track recurrence reduction weekly.",
}

PROBLEM_TRANSITIONS: dict[ProblemStatus, set[ProblemStatus]] = {
    ProblemStatus.open: set(ProblemStatus),
    ProblemStatus.investigating: set(ProblemStatus),
    ProblemStatus.known_error: set(ProblemStatus),
    ProblemStatus.resolved: set(ProblemStatus),
    ProblemStatus.closed: set(ProblemStatus),
}


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def normalize_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""

    # Ignore tool-injected ticket IDs (e.g. [TW-123], HP-4) for stable matching.
    text = SIMILARITY_TICKET_ID_RE.sub(" ", text)
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = re.sub(r"[^a-z0-9\s]", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def _normalize_tokens(value: str | None) -> list[str]:
    text = normalize_text(value)
    tokens = [token for token in text.split() if len(token) > 2 and token not in SIMILARITY_STOPWORDS]
    return tokens


def _next_problem_id(db: Session) -> str:
    ids = [row[0] for row in db.query(Problem.id).all()]
    max_num = 0
    for problem_id in ids:
        match = re.search(r"(\d+)$", problem_id or "")
        if not match:
            continue
        max_num = max(max_num, int(match.group(1)))
    return f"PB-{max_num + 1:04d}"


def _next_recommendation_id(db: Session) -> str:
    for _ in range(6):
        candidate = f"REC-{uuid4().hex[:8].upper()}"
        exists = db.query(Recommendation.id).filter(Recommendation.id == candidate).first()
        if not exists:
            return candidate
    return f"REC-{uuid4().hex.upper()}"


def compute_similarity_key(
    title: str,
    category: TicketCategory,
    description: str | None = None,
    tags: list[str] | None = None,
) -> str:
    primary_tag = _select_primary_similarity_tag(tags=tags, title=title, description=description)
    if primary_tag:
        return f"{category.value}|tag:{primary_tag}"[:255]

    title_tokens = _normalize_tokens(title)
    top_keywords: list[str] = []
    for token in title_tokens:
        if token not in top_keywords:
            top_keywords.append(token)
        if len(top_keywords) >= 3:
            break
    if not top_keywords:
        description_tokens = _normalize_tokens(description)
        token_counts = Counter(description_tokens)
        top_keywords = [token for token, _ in token_counts.most_common(3)]
    if not top_keywords:
        top_keywords = ["generic"]
    return f"{category.value}|kw:{'-'.join(top_keywords)}"[:255]


def _normalize_tag(tag: str | None) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", normalize_text(tag)).strip("_")
    return cleaned[:24]


def _normalize_tags(tags: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        tag = _normalize_tag(raw)
        if (
            not tag
            or tag in seen
            or any(tag.startswith(prefix) for prefix in SIMILARITY_NOISE_TAG_PREFIXES)
        ):
            continue
        seen.add(tag)
        normalized.append(tag)
    return normalized


def _problem_title_from_ticket(*, title: str, category: TicketCategory) -> str:
    cleaned = normalize_text(title)
    if not cleaned:
        return f"Recurring {category.value} incidents"
    return f"Recurring {category.value} incidents - {' '.join(cleaned.split()[:8])}"[:255]


def _ticket_created_at_for_problem_stats(ticket: Ticket) -> dt.datetime:
    value = getattr(ticket, "jira_created_at", None) or ticket.created_at
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _ticket_event_time(ticket: Ticket) -> dt.datetime:
    value = getattr(ticket, "jira_created_at", None) or ticket.created_at
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _ticket_similarity_tokens(ticket: Ticket) -> set[str]:
    return set(_normalize_tokens(f"{ticket.title} {ticket.description}"))


def _problem_similarity_tokens(problem: Problem, linked_tickets: list[Ticket]) -> set[str]:
    tokens = _extract_similarity_tokens(problem.similarity_key)
    tokens.update(_normalize_tokens(problem.title))
    for linked in linked_tickets[:8]:
        tokens.update(_ticket_similarity_tokens(linked))
    return tokens


def _jaccard_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    common = len(left.intersection(right))
    return common / max(1, len(left.union(right)))


def _problem_match_score(*, ticket: Ticket, similarity_key: str, problem: Problem, linked_tickets: list[Ticket]) -> float:
    if ticket.category != problem.category:
        return 0.0
    if similarity_key == problem.similarity_key:
        return 1.0
    left = _ticket_similarity_tokens(ticket)
    right = _problem_similarity_tokens(problem, linked_tickets)
    return _jaccard_overlap(left, right)


def _ticket_pair_similarity_score(ticket: Ticket, other: Ticket) -> float:
    if ticket.category != other.category:
        return 0.0
    left_key = compute_similarity_key(
        ticket.title,
        ticket.category,
        description=ticket.description,
        tags=ticket.tags,
    )
    right_key = compute_similarity_key(
        other.title,
        other.category,
        description=other.description,
        tags=other.tags,
    )
    if left_key == right_key:
        return 1.0
    return _jaccard_overlap(_ticket_similarity_tokens(ticket), _ticket_similarity_tokens(other))


def _find_similar_problem(
    db: Session,
    *,
    ticket: Ticket,
    similarity_key: str,
    min_score: float = PROBLEM_MATCH_SCORE_THRESHOLD,
) -> Problem | None:
    candidates = (
        db.query(Problem)
        .filter(Problem.category == ticket.category)
        .order_by(Problem.updated_at.desc())
        .all()
    )
    if not candidates:
        return None

    scored: list[tuple[float, Problem]] = []
    for problem in candidates:
        linked = (
            db.query(Ticket)
            .filter(Ticket.problem_id == problem.id)
            .order_by(Ticket.updated_at.desc())
            .all()
        )
        score = _problem_match_score(ticket=ticket, similarity_key=similarity_key, problem=problem, linked_tickets=linked)
        if score >= min_score:
            scored.append((score, problem))

    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
    return scored[0][1]


def _recent_similar_tickets(
    db: Session,
    *,
    ticket: Ticket,
    window_days: int = PROBLEM_TRIGGER_WINDOW_DAYS,
    min_score: float = PROBLEM_MATCH_SCORE_THRESHOLD,
) -> list[Ticket]:
    now = _utcnow()
    cutoff = now - dt.timedelta(days=max(1, window_days))
    candidates = (
        db.query(Ticket)
        .filter(Ticket.category == ticket.category)
        .all()
    )
    rows: list[Ticket] = []
    for candidate in candidates:
        if _ticket_event_time(candidate) < cutoff:
            continue
        if _ticket_pair_similarity_score(ticket, candidate) < min_score:
            continue
        rows.append(candidate)
    return rows


def _similarity_tag_score(tag: str, *, title_tokens: set[str], description_tokens: set[str]) -> int:
    score = 0
    if tag not in GENERIC_SIMILARITY_TAGS:
        score += 8
    if tag in title_tokens:
        score += 6
    if tag in description_tokens:
        score += 3
    if len(tag) <= 4:
        score += 1
    return score


def _select_primary_similarity_tag(*, tags: list[str] | None, title: str, description: str | None) -> str | None:
    normalized = _normalize_tags(tags)
    if not normalized:
        return None

    title_tokens = set(_normalize_tokens(title))
    description_tokens = set(_normalize_tokens(description))
    ranked = sorted(
        normalized,
        key=lambda tag: (
            -_similarity_tag_score(tag, title_tokens=title_tokens, description_tokens=description_tokens),
            len(tag),
            tag,
        ),
    )
    return ranked[0] if ranked else None


def _primary_tag_from_tickets(tickets: list[Ticket]) -> str | None:
    picks = Counter()
    for ticket in tickets:
        primary = _select_primary_similarity_tag(
            tags=ticket.tags,
            title=ticket.title,
            description=ticket.description,
        )
        if primary:
            picks[primary] += 1
    if not picks:
        return None
    ranked = sorted(picks.items(), key=lambda item: (-item[1], len(item[0]), item[0]))
    return ranked[0][0]


def _extract_similarity_tokens(similarity_key: str | None) -> set[str]:
    tokens = re.split(r"[^a-z0-9]+", (similarity_key or "").lower())
    return {
        token
        for token in tokens
        if token
        and len(token) > 2
        and token not in SIMILARITY_STOPWORDS
        and token not in GENERIC_SIMILARITY_TAGS
    }


def _find_existing_problem_by_tag(db: Session, *, category: TicketCategory, primary_tag: str | None) -> Problem | None:
    if not primary_tag:
        return None

    candidates = (
        db.query(Problem)
        .filter(Problem.category == category)
        .order_by(Problem.updated_at.desc())
        .all()
    )
    if not candidates:
        return None

    for include_closed in (False, True):
        for candidate in candidates:
            if not include_closed and candidate.status == ProblemStatus.closed:
                continue
            tokens = _extract_similarity_tokens(candidate.similarity_key)
            tokens.update(_normalize_tokens(candidate.title))
            if primary_tag in tokens:
                return candidate
    return None


def _derive_problem_title(tickets: list[Ticket], category: TicketCategory) -> str:
    title_tokens = Counter()
    for ticket in tickets:
        title_tokens.update(_normalize_tokens(ticket.title))
    words = [word for word, _ in title_tokens.most_common(3)]
    suffix = " ".join(words) if words else "recurring pattern"
    return f"Recurring {category.value} incidents - {suffix}"[:255]


def get_or_create_problem(
    db: Session,
    *,
    similarity_key: str,
    title: str,
    category: TicketCategory,
) -> Problem:
    existing = db.query(Problem).filter(Problem.similarity_key == similarity_key).first()
    if existing:
        return existing

    now = _utcnow()
    problem = Problem(
        id=_next_problem_id(db),
        title=_problem_title_from_ticket(title=title, category=category),
        category=category,
        status=ProblemStatus.investigating,
        similarity_key=similarity_key,
        created_at=now,
        updated_at=now,
        last_seen_at=now,
        occurrences_count=0,
        active_count=0,
    )
    db.add(problem)
    db.flush()
    return problem


def recompute_problem_stats(db: Session, problem_id: str) -> Problem | None:
    problem = db.query(Problem).filter(Problem.id == problem_id).first()
    if not problem:
        return None

    linked = db.query(Ticket).filter(Ticket.problem_id == problem.id).all()
    problem.occurrences_count = len(linked)
    problem.active_count = sum(1 for ticket in linked if ticket.status in ACTIVE_TICKET_STATUSES)
    problem.last_seen_at = max(
        (_ticket_created_at_for_problem_stats(ticket) for ticket in linked),
        default=problem.last_seen_at,
    )
    problem.updated_at = _utcnow()
    db.add(problem)
    db.flush()
    return problem


def _detach_if_problem_mismatch(
    db: Session,
    *,
    ticket: Ticket,
    similarity_key: str,
    min_score: float = PROBLEM_MATCH_SCORE_THRESHOLD,
) -> None:
    if not ticket.problem_id:
        return
    current = db.query(Problem).filter(Problem.id == ticket.problem_id).first()
    if not current:
        ticket.problem_id = None
        db.add(ticket)
        db.flush()
        return
    linked = (
        db.query(Ticket)
        .filter(Ticket.problem_id == current.id)
        .order_by(Ticket.updated_at.desc())
        .all()
    )
    score = _problem_match_score(ticket=ticket, similarity_key=similarity_key, problem=current, linked_tickets=linked)
    if score >= min_score:
        return
    old_problem_id = current.id
    ticket.problem_id = None
    db.add(ticket)
    db.flush()
    recompute_problem_stats(db, old_problem_id)


def link_ticket_to_problem(db: Session, ticket: Ticket) -> Problem | None:
    if not ticket.title or not ticket.category:
        return None

    similarity_key = compute_similarity_key(
        ticket.title,
        ticket.category,
        description=ticket.description,
        tags=ticket.tags,
    )
    _detach_if_problem_mismatch(db, ticket=ticket, similarity_key=similarity_key)

    existing = _find_similar_problem(db, ticket=ticket, similarity_key=similarity_key)
    if existing:
        if ticket.problem_id != existing.id:
            ticket.problem_id = existing.id
            db.add(ticket)
            db.flush()
        recompute_problem_stats(db, existing.id)
        return existing

    candidates = _recent_similar_tickets(db, ticket=ticket)
    if all(item.id != ticket.id for item in candidates):
        candidates.append(ticket)
    # Only launch a new Problem if enough similar incidents occurred recently.
    if len(candidates) < PROBLEM_TRIGGER_MIN_COUNT:
        return None

    current = db.query(Problem).filter(Problem.similarity_key == similarity_key).first()
    created = current is None
    problem = current or get_or_create_problem(
        db,
        similarity_key=similarity_key,
        title=ticket.title,
        category=ticket.category,
    )

    for item in candidates:
        if item.problem_id == problem.id:
            continue
        item.problem_id = problem.id
        db.add(item)
    db.flush()
    recompute_problem_stats(db, problem.id)
    _emit_problem_recommendations(db, problem, candidates, created=created)
    return problem


def _recompute_problem_counters(db: Session, problem: Problem) -> None:
    recompute_problem_stats(db, problem.id)


def _upsert_recommendation(
    db: Session,
    *,
    title: str,
    description: str,
    rec_type: RecommendationType,
    related_tickets: list[str],
    impact: RecommendationImpact,
    confidence: int,
) -> None:
    existing = db.query(Recommendation).filter(Recommendation.title == title).first()
    if existing:
        existing.description = description
        existing.type = rec_type
        existing.related_tickets = related_tickets
        existing.impact = impact
        existing.confidence = confidence
        db.add(existing)
        return
    db.add(
        Recommendation(
            id=_next_recommendation_id(db),
            type=rec_type,
            title=title,
            description=description,
            related_tickets=related_tickets,
            impact=impact,
            confidence=confidence,
        )
    )


def _emit_problem_recommendations(db: Session, problem: Problem, tickets: list[Ticket], *, created: bool) -> None:
    related_ticket_ids = [ticket.id for ticket in tickets]
    if created:
        _upsert_recommendation(
            db,
            title=f"Recurring pattern detected -> {problem.id}",
            description=(
                f"{len(tickets)} similar {problem.category.value} incidents detected in the current window. "
                f"Problem {problem.id} opened for root cause analysis."
            ),
            rec_type=RecommendationType.pattern,
            related_tickets=related_ticket_ids,
            impact=RecommendationImpact.high,
            confidence=90,
        )
        _upsert_recommendation(
            db,
            title=f"Workflow reinforcement for {problem.id}",
            description=(
                f"Create/refresh runbook and auto-routing for recurring {problem.category.value} incidents "
                f"linked to {problem.id}."
            ),
            rec_type=RecommendationType.workflow,
            related_tickets=related_ticket_ids,
            impact=RecommendationImpact.medium,
            confidence=80,
        )

    if problem.workaround or problem.permanent_fix:
        snippet = problem.permanent_fix or problem.workaround or ""
        _upsert_recommendation(
            db,
            title=f"Solution update for {problem.id}",
            description=f"Known solution guidance: {snippet[:220]}",
            rec_type=RecommendationType.solution,
            related_tickets=related_ticket_ids,
            impact=RecommendationImpact.high if problem.permanent_fix else RecommendationImpact.medium,
            confidence=88 if problem.permanent_fix else 72,
        )


def upsert_problem(db: Session, *, similarity_key: str, tickets: list[Ticket]) -> tuple[Problem, bool, bool]:
    if not tickets:
        raise ValueError("tickets_required")
    category = tickets[0].category
    primary_tag = _primary_tag_from_tickets(tickets)
    existing = db.query(Problem).filter(Problem.similarity_key == similarity_key).first()
    if not existing:
        existing = _find_existing_problem_by_tag(db, category=category, primary_tag=primary_tag)
    created = False
    updated = False
    now = _utcnow()

    if not existing:
        problem = Problem(
            id=_next_problem_id(db),
            title=_derive_problem_title(tickets, category),
            category=category,
            status=ProblemStatus.investigating,
            similarity_key=similarity_key,
            created_at=now,
            updated_at=now,
            last_seen_at=max(ticket.created_at for ticket in tickets),
            occurrences_count=0,
            active_count=0,
        )
        db.add(problem)
        created = True
    else:
        problem = existing
        if problem.similarity_key != similarity_key:
            collision = (
                db.query(Problem.id)
                .filter(Problem.similarity_key == similarity_key, Problem.id != problem.id)
                .first()
            )
            if not collision:
                problem.similarity_key = similarity_key
                updated = True
        if problem.status == ProblemStatus.open:
            problem.status = ProblemStatus.investigating
            updated = True
        problem.last_seen_at = max([problem.last_seen_at or now, *(ticket.created_at for ticket in tickets)])
        problem.updated_at = now
        db.add(problem)

    db.flush()
    linked_count = 0
    for ticket in tickets:
        if ticket.problem_id != problem.id:
            ticket.problem_id = problem.id
            db.add(ticket)
            linked_count += 1
    if linked_count:
        updated = True

    db.flush()
    _recompute_problem_counters(db, problem)
    _emit_problem_recommendations(db, problem, tickets, created=created)
    db.commit()
    db.refresh(problem)
    return problem, created, updated


def detect_problems(
    db: Session,
    *,
    window_days: int = PROBLEM_TRIGGER_WINDOW_DAYS,
    min_count: int = PROBLEM_TRIGGER_MIN_COUNT,
) -> dict[str, int]:
    now = _utcnow()
    cutoff = now - dt.timedelta(days=window_days)
    candidates = sorted(
        [ticket for ticket in db.query(Ticket).all() if _ticket_event_time(ticket) >= cutoff],
        key=_ticket_event_time,
    )

    grouped: dict[str, list[Ticket]] = defaultdict(list)
    for ticket in candidates:
        key = compute_similarity_key(
            title=ticket.title,
            description=ticket.description,
            category=ticket.category,
            tags=ticket.tags,
        )
        grouped[key].append(ticket)

    processed_groups = 0
    created = 0
    updated = 0
    linked = 0

    for similarity_key, tickets in grouped.items():
        if len(tickets) < min_count:
            continue
        processed_groups += 1
        before_links = sum(1 for ticket in tickets if ticket.problem_id)
        _, was_created, was_updated = upsert_problem(db, similarity_key=similarity_key, tickets=tickets)
        after_links = len(tickets)
        linked += max(0, after_links - before_links)
        created += 1 if was_created else 0
        updated += 1 if was_updated else 0

    return {
        "processed_groups": processed_groups,
        "created": created,
        "updated": updated,
        "linked": linked,
    }


def list_problems(
    db: Session,
    *,
    status: ProblemStatus | None = None,
    category: TicketCategory | None = None,
    active_only: bool = False,
) -> list[Problem]:
    query = db.query(Problem).options(joinedload(Problem.tickets))
    if status:
        query = query.filter(Problem.status == status)
    if category:
        query = query.filter(Problem.category == category)
    if active_only:
        query = query.filter(Problem.active_count > 0)
    return query.order_by(Problem.updated_at.desc()).all()


def get_problem(db: Session, problem_id: str) -> Problem | None:
    return (
        db.query(Problem)
        .options(joinedload(Problem.tickets))
        .filter(Problem.id == problem_id)
        .first()
    )


def _as_utc_timestamp(value: dt.datetime | None) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.timestamp()


def derive_problem_assignee(problem: Problem, *, tickets: list[Ticket] | None = None) -> str | None:
    linked = list(tickets if tickets is not None else (problem.tickets or []))
    assignee_stats: dict[str, tuple[int, float]] = {}

    for ticket in linked:
        assignee = (ticket.assignee or "").strip()
        if not assignee:
            continue
        count, latest = assignee_stats.get(assignee, (0, 0.0))
        assignee_stats[assignee] = (
            count + 1,
            max(latest, _as_utc_timestamp(ticket.updated_at)),
        )

    if not assignee_stats:
        return None
    ranked = sorted(
        assignee_stats.items(),
        # Prefer the most recently active assignee so manual reassignment
        # is reflected immediately in Problem views.
        key=lambda item: (-item[1][1], -item[1][0], item[0].casefold()),
    )
    return ranked[0][0]


def assign_problem_assignee(
    db: Session,
    problem: Problem,
    *,
    mode: str,
    assignee: str | None = None,
) -> tuple[str, int]:
    linked = db.query(Ticket).filter(Ticket.problem_id == problem.id).all()
    if not linked:
        raise ValueError("problem_has_no_linked_tickets")

    normalized_mode = (mode or "").strip().lower()
    if normalized_mode not in {"auto", "manual"}:
        raise ValueError("invalid_assignment_mode")

    selected_assignee: str | None
    auto_mode = normalized_mode == "auto"
    if auto_mode:
        selected_assignee = select_best_assignee(
            db,
            category=problem.category,
            priority=TicketPriority.high,
        )
        if not selected_assignee:
            selected_assignee = derive_problem_assignee(problem, tickets=linked)
    else:
        requested = (assignee or "").strip()
        if not requested:
            raise ValueError("assignee_required_for_manual_mode")
        allowed = {user.name.casefold(): user.name for user in list_assignees(db)}
        selected_assignee = allowed.get(requested.casefold())
        if not selected_assignee:
            raise ValueError("assignee_not_assignable")

    if not selected_assignee:
        raise ValueError("assignee_unavailable")

    now = _utcnow()
    updated_tickets = 0
    expected_model_version = "smart-v1" if auto_mode else "manual"

    for ticket in linked:
        changed = False
        if ticket.assignee != selected_assignee:
            ticket.assignee = selected_assignee
            ticket.assignment_change_count = int(ticket.assignment_change_count or 0) + 1
            changed = True

        if bool(ticket.auto_assignment_applied) != auto_mode:
            ticket.auto_assignment_applied = auto_mode
            changed = True

        if (ticket.assignment_model_version or "").strip() != expected_model_version:
            ticket.assignment_model_version = expected_model_version
            changed = True

        if not changed:
            continue

        if ticket.first_action_at is None:
            ticket.first_action_at = now
        ticket.updated_at = now
        db.add(ticket)
        updated_tickets += 1

    problem.updated_at = now
    db.add(problem)
    _recompute_problem_counters(db, problem)
    db.commit()
    db.refresh(problem)
    return selected_assignee, updated_tickets


def _summary_snippet(text: str | None, *, max_len: int = 180) -> str | None:
    value = re.sub(r"\s+", " ", (text or "").strip())
    if not value:
        return None
    if len(value) <= max_len:
        return value
    return value[: max_len - 3].rstrip() + "..."


def _top_problem_keywords(problem: Problem, linked: list[Ticket], *, limit: int = 3) -> list[str]:
    counts = Counter()
    counts.update(_normalize_tokens(problem.title))
    for ticket in linked:
        counts.update(_normalize_tokens(ticket.title))
        counts.update(_normalize_tokens(ticket.description))
    return [token for token, _ in counts.most_common(limit)]


def _field_suggestion_from_ai(
    ai_recommendations: list[str],
    *,
    index: int,
    prefix: str,
) -> str | None:
    if index >= len(ai_recommendations):
        return None
    suggestion = _summary_snippet(ai_recommendations[index], max_len=220)
    if not suggestion:
        return None
    return f"{prefix}: {suggestion}"


def _suggestion_confidence_from_origin(origin: str, *, rank: int = 0) -> int:
    base = {
        "existing": 92,
        "resolved": 86,
        "ai": 78,
        "fallback": 66,
    }.get(origin, 72)
    return max(50, min(96, base - (rank * 4)))


def _field_confidence(origin: str) -> int:
    return {
        "existing": 92,
        "resolved": 86,
        "ai": 78,
        "fallback": 66,
    }.get(origin, 72)


def build_problem_ai_suggestions(db: Session, problem: Problem, *, tickets: list[Ticket] | None = None, limit: int = 5) -> dict[str, object]:
    linked = list(tickets if tickets is not None else (problem.tickets or []))
    suggestion_rows: list[tuple[str, str]] = []
    seen: set[str] = set()

    def push(item: str | None, *, origin: str) -> None:
        if not item:
            return
        key = item.casefold()
        if key in seen:
            return
        seen.add(key)
        suggestion_rows.append((item, origin))

    permanent_fix_snippet = _summary_snippet(problem.permanent_fix)
    if permanent_fix_snippet:
        push(f"Apply permanent fix: {permanent_fix_snippet}", origin="existing")
    workaround_snippet = _summary_snippet(problem.workaround)
    if workaround_snippet:
        push(f"Use workaround while root cause is being fixed: {workaround_snippet}", origin="existing")
    root_cause_snippet = _summary_snippet(problem.root_cause)
    if root_cause_snippet:
        push(f"Validate root cause in production telemetry: {root_cause_snippet}", origin="existing")

    resolved = sorted(
        [
            ticket
            for ticket in linked
            if ticket.status in {TicketStatus.resolved, TicketStatus.closed} and (ticket.resolution or "").strip()
        ],
        key=lambda item: item.updated_at,
        reverse=True,
    )
    for ticket in resolved[:2]:
        resolution_snippet = _summary_snippet(ticket.resolution)
        if resolution_snippet:
            push(f"Reuse validated resolution from {ticket.id}: {resolution_snippet}", origin="resolved")

    description_parts = [
        problem.root_cause or "",
        problem.workaround or "",
        problem.permanent_fix or "",
        " ".join((ticket.title or "") for ticket in linked[:6]),
    ]
    description = " ".join(part for part in description_parts if part).strip()
    _, _, ai_recommendations = classify_ticket(problem.title, description or problem.title)
    ai_scored = score_recommendations(
        ai_recommendations,
        start_confidence=80,
        rank_decay=6,
        floor=58,
        ceiling=90,
    )
    ai_confidence_map = {
        str(item["text"]).casefold(): int(item["confidence"])
        for item in ai_scored
        if str(item.get("text", "")).strip()
    }
    for item in ai_scored:
        push(_summary_snippet(str(item["text"])), origin="ai")

    if not suggestion_rows:
        push("Collect logs and timeline evidence to confirm a single root cause before rollout.", origin="fallback")
        push("Publish a runbook with rollback and verification checks after applying the fix.", origin="fallback")

    assignee = derive_problem_assignee(problem, tickets=linked)
    if not assignee:
        assignee = select_best_assignee(db, category=problem.category, priority=TicketPriority.high)

    keywords = _top_problem_keywords(problem, linked)
    keyword_line = ", ".join(keywords) if keywords else problem.category.value

    root_cause_source = "fallback"
    if root_cause_snippet:
        root_cause_suggestion = root_cause_snippet
        root_cause_source = "existing"
    else:
        root_cause_suggestion = _field_suggestion_from_ai(
            ai_recommendations,
            index=0,
            prefix="RCA hypothesis",
        )
        if root_cause_suggestion:
            root_cause_source = "ai"
    if not root_cause_suggestion:
        root_cause_suggestion = (
            f"Hypothesis around recurring pattern ({keyword_line}). {ROOT_CAUSE_HINTS.get(problem.category, ROOT_CAUSE_HINTS[TicketCategory.problem])}"
        )
        root_cause_source = "fallback"

    workaround_source = "fallback"
    workaround_suggestion = workaround_snippet
    if workaround_suggestion:
        workaround_source = "existing"
    if not workaround_suggestion and resolved:
        resolution_snippet = _summary_snippet(resolved[0].resolution)
        if resolution_snippet:
            workaround_suggestion = f"Use validated temporary action from {resolved[0].id}: {resolution_snippet}"
            workaround_source = "resolved"
    if not workaround_suggestion:
        workaround_suggestion = _field_suggestion_from_ai(
            ai_recommendations,
            index=1,
            prefix="Temporary workaround",
        )
        if workaround_suggestion:
            workaround_source = "ai"
    if not workaround_suggestion:
        workaround_suggestion = WORKAROUND_HINTS.get(problem.category, WORKAROUND_HINTS[TicketCategory.problem])
        workaround_source = "fallback"

    permanent_fix_source = "fallback"
    if permanent_fix_snippet:
        permanent_fix_suggestion = permanent_fix_snippet
        permanent_fix_source = "existing"
    else:
        permanent_fix_suggestion = _field_suggestion_from_ai(
            ai_recommendations,
            index=2,
            prefix="Permanent corrective action",
        )
        if permanent_fix_suggestion:
            permanent_fix_source = "ai"
    if not permanent_fix_suggestion:
        permanent_fix_suggestion = PERMANENT_FIX_HINTS.get(
            problem.category,
            PERMANENT_FIX_HINTS[TicketCategory.problem],
        )
        permanent_fix_source = "fallback"

    max_items = max(1, limit)
    picked = suggestion_rows[:max_items]
    suggestions_scored = []
    for idx, (text, origin) in enumerate(picked):
        confidence = _suggestion_confidence_from_origin(origin, rank=idx)
        if origin == "ai":
            confidence = ai_confidence_map.get(text.casefold(), confidence)
        suggestions_scored.append({"text": text, "confidence": confidence})

    return {
        "problem_id": problem.id,
        "category": problem.category,
        "assignee": assignee,
        "suggestions": [item["text"] for item in suggestions_scored],
        "suggestions_scored": suggestions_scored,
        "root_cause_suggestion": root_cause_suggestion,
        "workaround_suggestion": workaround_suggestion,
        "permanent_fix_suggestion": permanent_fix_suggestion,
        "root_cause_confidence": _field_confidence(root_cause_source),
        "workaround_confidence": _field_confidence(workaround_source),
        "permanent_fix_confidence": _field_confidence(permanent_fix_source),
    }


def _validate_problem_transition(current: ProblemStatus, target: ProblemStatus) -> None:
    allowed = PROBLEM_TRANSITIONS.get(current, {current})
    if target not in allowed:
        raise ValueError("invalid_problem_status_transition")


def update_problem(db: Session, problem: Problem, payload: ProblemUpdate) -> Problem:
    target_status = payload.status or problem.status
    _validate_problem_transition(problem.status, target_status)
    resolution_comment = (payload.resolution_comment or "").strip()

    if payload.root_cause is not None:
        problem.root_cause = payload.root_cause
    if payload.workaround is not None:
        problem.workaround = payload.workaround
    if payload.permanent_fix is not None:
        problem.permanent_fix = payload.permanent_fix

    if target_status in {ProblemStatus.resolved, ProblemStatus.closed}:
        if not resolution_comment:
            raise ValueError("resolution_comment_required")
        if not (problem.root_cause and problem.permanent_fix):
            raise ValueError("problem_resolution_requires_root_cause_and_permanent_fix")

    problem.status = target_status
    if target_status == ProblemStatus.resolved:
        problem.resolved_at = _utcnow()
    elif target_status in {ProblemStatus.open, ProblemStatus.investigating, ProblemStatus.known_error}:
        problem.resolved_at = None
    problem.updated_at = _utcnow()
    _recompute_problem_counters(db, problem)

    linked_tickets = db.query(Ticket).filter(Ticket.problem_id == problem.id).all()
    _emit_problem_recommendations(db, problem, linked_tickets, created=False)

    db.commit()
    db.refresh(problem)
    return problem


def link_ticket(db: Session, problem: Problem, ticket: Ticket) -> bool:
    if ticket.problem_id == problem.id:
        return False
    ticket.problem_id = problem.id
    db.add(ticket)
    _recompute_problem_counters(db, problem)
    db.commit()
    return True


def unlink_ticket(db: Session, problem: Problem, ticket: Ticket) -> bool:
    if ticket.problem_id != problem.id:
        return False
    ticket.problem_id = None
    db.add(ticket)
    _recompute_problem_counters(db, problem)
    db.commit()
    return True


def resolve_linked_tickets(
    db: Session,
    problem: Problem,
    *,
    actor: str,
    resolution_comment: str,
) -> int:
    linked = (
        db.query(Ticket)
        .filter(Ticket.problem_id == problem.id, Ticket.status.in_(list(ACTIVE_TICKET_STATUSES)))
        .all()
    )
    resolved_count = 0
    for ticket in linked:
        updated = update_status(
            db,
            ticket.id,
            TicketStatus.resolved,
            actor=actor,
            resolution_comment=resolution_comment,
        )
        if updated:
            resolved_count += 1
    db.refresh(problem)
    _recompute_problem_counters(db, problem)
    db.commit()
    return resolved_count


def problem_analytics_summary(db: Session) -> dict[str, object]:
    problems = db.query(Problem).all()
    by_status = Counter(problem.status.value for problem in problems)
    top_candidates = [
        problem
        for problem in problems
        if problem.status in {ProblemStatus.open, ProblemStatus.investigating, ProblemStatus.known_error}
    ]
    top = sorted(
        top_candidates,
        key=lambda problem: (problem.active_count, problem.occurrences_count, problem.updated_at),
        reverse=True,
    )[:6]
    top_payload = []
    for problem in top:
        linked = (
            db.query(Ticket)
            .filter(Ticket.problem_id == problem.id)
            .order_by(Ticket.updated_at.desc())
            .all()
        )
        ticket_ids = [ticket.id for ticket in linked]
        latest = linked[0] if linked else None
        priority_order = {
            "critical": 4,
            "high": 3,
            "medium": 2,
            "low": 1,
        }
        highest_priority = "low"
        for ticket in linked:
            level = ticket.priority.value
            if priority_order[level] > priority_order[highest_priority]:
                highest_priority = level
        fix_text = (problem.permanent_fix or "").strip()
        workaround_text = (problem.workaround or "").strip()
        if fix_text:
            recommendation = fix_text
            recommendation_confidence = 90
        elif workaround_text:
            recommendation = workaround_text
            recommendation_confidence = 80
        else:
            recommendation = "Run RCA and define a permanent corrective action."
            recommendation_confidence = 65
        top_payload.append(
            {
                "id": problem.id,
                "title": problem.title,
                "status": problem.status.value,
                "occurrences_count": problem.occurrences_count,
                "active_count": problem.active_count,
                "category": problem.category.value,
                "latest_ticket_id": latest.id if latest else "",
                "latest_updated_at": latest.updated_at.isoformat() if latest else problem.updated_at.isoformat(),
                "ticket_ids": ticket_ids,
                "highest_priority": highest_priority,
                "problem_count": 1,
                "problem_triggered": True,
                "trigger_reasons": ["5_in_7_days"],
                "recent_occurrences_7d": problem.occurrences_count,
                "same_day_peak": max(1, min(problem.occurrences_count, 4)),
                "same_day_peak_date": (latest.updated_at.date().isoformat() if latest else None),
                "ai_recommendation": recommendation,
                "ai_recommendation_confidence": recommendation_confidence,
            }
        )
    return {
        "total": len(problems),
        "open": by_status.get(ProblemStatus.open.value, 0),
        "investigating": by_status.get(ProblemStatus.investigating.value, 0),
        "known_error": by_status.get(ProblemStatus.known_error.value, 0),
        "resolved": by_status.get(ProblemStatus.resolved.value, 0),
        "closed": by_status.get(ProblemStatus.closed.value, 0),
        "active_total": sum(problem.active_count for problem in problems),
        "top": top_payload,
    }
