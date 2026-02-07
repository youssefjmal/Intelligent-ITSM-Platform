"""Schemas for email log responses."""

from __future__ import annotations

import datetime as dt
from pydantic import BaseModel

from app.models.enums import EmailKind


class EmailLogOut(BaseModel):
    to: str
    subject: str
    body: str
    sent_at: dt.datetime
    kind: EmailKind

    class Config:
        from_attributes = True
