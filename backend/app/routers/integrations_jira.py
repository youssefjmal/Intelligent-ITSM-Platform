"""Inbound Jira integration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.core.exceptions import AuthenticationException, BadRequestError
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.integrations.jira.schemas import JiraReconcileRequest, JiraReconcileResult, JiraWebhookResponse
from app.integrations.jira.service import (
    LEGACY_WEBHOOK_SIGNATURE_HEADER,
    WEBHOOK_SECRET_HEADER,
    SyncCounts,
    reconcile,
    sync_issue_by_key,
    sync_issue_from_webhook_payload,
    validate_webhook_secret,
)
from app.models.enums import UserRole
from app.models.user import User

router = APIRouter(dependencies=[Depends(rate_limit("default"))])


@router.post("/integrations/jira/webhook", response_model=JiraWebhookResponse)
@router.post("/integrations/jira/upsert", response_model=JiraWebhookResponse, deprecated=True)
async def jira_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_jira_webhook_secret: str | None = Header(default=None, alias=WEBHOOK_SECRET_HEADER),
    x_signature: str | None = Header(default=None, alias=LEGACY_WEBHOOK_SIGNATURE_HEADER),
) -> JiraWebhookResponse:
    raw_body = await request.body()
    if not validate_webhook_secret(
        x_jira_webhook_secret,
        signature_header=x_signature,
        raw_body=raw_body,
    ):
        raise AuthenticationException("invalid_webhook_secret", error_code="INVALID_WEBHOOK_SECRET", status_code=401)

    payload = await request.json()
    if not isinstance(payload, dict):
        raise BadRequestError("invalid_payload")
    try:
        return sync_issue_from_webhook_payload(db, payload)
    except ValueError as exc:
        raise BadRequestError(str(exc))


@router.post("/integrations/jira/reconcile", response_model=JiraReconcileResult)
def jira_reconcile(
    payload: JiraReconcileRequest = Body(default=JiraReconcileRequest()),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _require_admin: None = Depends(require_roles(UserRole.admin)),
) -> JiraReconcileResult:
    try:
        return reconcile(db, payload)
    except ValueError as exc:
        raise BadRequestError(str(exc))


@router.post("/integrations/jira/sync/{issue_key}", response_model=dict)
def jira_sync_single(
    issue_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _require_admin: None = Depends(require_roles(UserRole.admin)),
) -> dict:
    """Force-sync a single Jira issue into the local DB by its key (e.g. HP-42).

    Useful when a ticket was created in Jira but didn't arrive via webhook or
    the auto-reconcile cycle hasn't run yet.
    """
    key = (issue_key or "").strip().upper()
    if not key:
        raise BadRequestError("missing_issue_key")
    try:
        counts: SyncCounts = sync_issue_by_key(db, key)
    except ValueError as exc:
        raise BadRequestError(str(exc))
    return {
        "issue_key": key,
        "tickets_upserted": counts.tickets_upserted,
        "comments_upserted": counts.comments_upserted,
        "comments_updated": counts.comments_updated,
        "skipped": counts.skipped,
    }
