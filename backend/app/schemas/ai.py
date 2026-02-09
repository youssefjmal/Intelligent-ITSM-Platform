"""Schemas for AI classification/chat requests and responses."""

from __future__ import annotations

from pydantic import BaseModel

from app.models.enums import TicketCategory, TicketPriority


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    locale: str | None = None


class TicketDraft(BaseModel):
    title: str
    description: str
    priority: TicketPriority
    category: TicketCategory
    tags: list[str] = []
    assignee: str | None = None


class ChatResponse(BaseModel):
    reply: str
    action: str | None = None
    ticket: TicketDraft | None = None


class ClassificationRequest(BaseModel):
    title: str
    description: str


class ClassificationResponse(BaseModel):
    priority: TicketPriority
    category: TicketCategory
    recommendations: list[str]
