"""Schemas for AI classification/chat requests and responses."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.models.enums import TicketCategory, TicketPriority
from app.core.ticket_limits import MAX_TAG_LEN, MAX_TAGS
from app.core.sanitize import clean_list, clean_multiline, clean_single_line

MAX_CHAT_MESSAGES = 40
MAX_CHAT_CONTENT_LEN = 4000
MAX_TITLE_LEN = 120
MAX_DESCRIPTION_LEN = 4000
ALLOWED_CHAT_ROLES = {"user", "assistant", "system", "tool"}


class ChatMessage(BaseModel):
    role: str
    content: str = Field(min_length=1, max_length=MAX_CHAT_CONTENT_LEN)

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: str) -> str:
        role = clean_single_line(value).lower()
        if role not in ALLOWED_CHAT_ROLES:
            raise ValueError("invalid_role")
        return role

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        return clean_multiline(value)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_CHAT_MESSAGES)
    locale: str | None = Field(default=None, max_length=16)

    @field_validator("locale", mode="before")
    @classmethod
    def normalize_locale(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None


class TicketDraft(BaseModel):
    title: str = Field(min_length=3, max_length=MAX_TITLE_LEN)
    description: str = Field(min_length=5, max_length=MAX_DESCRIPTION_LEN)
    priority: TicketPriority
    category: TicketCategory
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    assignee: str | None = Field(default=None, max_length=80)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return clean_single_line(value)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return clean_multiline(value)

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return clean_list(value, max_items=MAX_TAGS, item_max_length=MAX_TAG_LEN)

    @field_validator("assignee", mode="before")
    @classmethod
    def normalize_assignee(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None


class ChatResponse(BaseModel):
    reply: str
    action: str | None = None
    ticket: TicketDraft | None = None


class ClassificationRequest(BaseModel):
    title: str = Field(min_length=3, max_length=MAX_TITLE_LEN)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LEN)
    locale: str | None = Field(default=None, max_length=16)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return clean_single_line(value)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: str | None) -> str:
        return clean_multiline(value)

    @field_validator("locale", mode="before")
    @classmethod
    def normalize_locale(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None


class AIRecommendationOut(BaseModel):
    text: str
    confidence: int = Field(ge=0, le=100)


class ClassificationResponse(BaseModel):
    priority: TicketPriority
    category: TicketCategory
    recommendations: list[str]
    recommendations_scored: list[AIRecommendationOut] = Field(default_factory=list)
    recommendations_embedding: list[str] = Field(default_factory=list)
    recommendations_embedding_scored: list[AIRecommendationOut] = Field(default_factory=list)
    recommendations_llm: list[str] = Field(default_factory=list)
    recommendations_llm_scored: list[AIRecommendationOut] = Field(default_factory=list)
    recommendation_mode: str = "llm"
    similarity_found: bool = False
    assignee: str | None = None
