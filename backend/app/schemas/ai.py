"""Schemas for AI classification/chat requests and responses."""

from __future__ import annotations

from pydantic import BaseModel

from app.models.enums import TicketCategory, TicketPriority


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    reply: str


class ClassificationRequest(BaseModel):
    title: str
    description: str


class ClassificationResponse(BaseModel):
    priority: TicketPriority
    category: TicketCategory
    recommendations: list[str]
