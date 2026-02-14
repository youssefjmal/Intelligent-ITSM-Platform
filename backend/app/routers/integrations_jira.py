"""Inbound Jira integration endpoints (n8n-friendly)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationException, BadRequestError
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.integrations.jira.schemas import JiraReconcileRequest, JiraReconcileResult, JiraUpsertResult
from app.integrations.jira.service import (
    SIGNATURE_HEADER,
    SYNC_ORIGIN_HEADER,
    is_loopback_sync,
    reconcile,
    upsert_from_payload,
    validate_signature,
)

router = APIRouter(dependencies=[Depends(rate_limit("auth"))])


@router.post("/integrations/jira/upsert", response_model=JiraUpsertResult)
async def jira_upsert(
    request: Request,
    db: Session = Depends(get_db),
    x_signature: str | None = Header(default=None, alias=SIGNATURE_HEADER),
    x_sync_origin: str | None = Header(default=None, alias=SYNC_ORIGIN_HEADER),
) -> JiraUpsertResult:
    raw_body = await request.body()
    if not validate_signature(raw_body=raw_body, signature_header=x_signature):
        raise AuthenticationException("invalid_signature", error_code="INVALID_SIGNATURE", status_code=401)

    payload = await request.json()
    if not isinstance(payload, dict):
        raise BadRequestError("invalid_payload")

    if is_loopback_sync(payload=payload, sync_origin=x_sync_origin):
        key = str(payload.get("issueKey") or ((payload.get("issue") or {}).get("key")) or "unknown")
        return JiraUpsertResult(jira_key=key, created=False, updated=False)

    return upsert_from_payload(db, payload)


@router.post("/integrations/jira/reconcile", response_model=JiraReconcileResult)
def jira_reconcile(
    payload: JiraReconcileRequest,
    db: Session = Depends(get_db),
) -> JiraReconcileResult:
    return reconcile(db, payload)
