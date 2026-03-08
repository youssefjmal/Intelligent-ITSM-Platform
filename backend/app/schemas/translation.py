"""Schemas for bilingual translation APIs."""

from __future__ import annotations

import enum

from pydantic import BaseModel, Field, field_validator

from app.core.sanitize import clean_list, clean_multiline

_MAX_TEXT_LEN = 8000
_MAX_SCOPE_ITEMS = 4
_DEFAULT_LIMIT = 80
_MAX_LIMIT = 400


class TranslationScope(str, enum.Enum):
    tickets = "tickets"
    problems = "problems"
    recommendations = "recommendations"
    kb_chunks = "kb_chunks"


_DEFAULT_SCOPES = [
    TranslationScope.tickets,
    TranslationScope.problems,
    TranslationScope.recommendations,
]


class BilingualTextOut(BaseModel):
    en: str
    fr: str


class TicketCommentTranslationOut(BaseModel):
    id: str
    author: str
    jira_comment_id: str | None = None
    content: BilingualTextOut


class TicketTranslationOut(BaseModel):
    id: str
    source: str
    jira_key: str | None = None
    jira_issue_id: str | None = None
    title: BilingualTextOut
    description: BilingualTextOut
    resolution: BilingualTextOut | None = None
    comments: list[TicketCommentTranslationOut] = Field(default_factory=list)


class ProblemTranslationOut(BaseModel):
    id: str
    title: BilingualTextOut
    root_cause: BilingualTextOut | None = None
    workaround: BilingualTextOut | None = None
    permanent_fix: BilingualTextOut | None = None


class RecommendationTranslationOut(BaseModel):
    id: str
    title: BilingualTextOut
    description: BilingualTextOut
    related_tickets: list[str] = Field(default_factory=list)


class KBChunkTranslationOut(BaseModel):
    id: int
    source_type: str
    jira_key: str | None = None
    jira_issue_id: str | None = None
    comment_id: str | None = None
    content: BilingualTextOut


class TranslationDatasetRequest(BaseModel):
    scopes: list[TranslationScope] = Field(default_factory=lambda: list(_DEFAULT_SCOPES), min_length=1, max_length=_MAX_SCOPE_ITEMS)
    include_comments: bool = True
    jira_only: bool = False
    limit_per_scope: int = Field(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT)
    offset: int = Field(default=0, ge=0, le=5000)

    @field_validator("scopes", mode="before")
    @classmethod
    def normalize_scopes(cls, value: list[str | TranslationScope] | None) -> list[TranslationScope]:
        raw = value or list(_DEFAULT_SCOPES)
        deduped: list[TranslationScope] = []
        seen: set[TranslationScope] = set()
        for item in raw:
            scope = item if isinstance(item, TranslationScope) else TranslationScope(str(item).strip().lower())
            if scope in seen:
                continue
            seen.add(scope)
            deduped.append(scope)
        return deduped


class TranslationDatasetSummaryOut(BaseModel):
    requested_scopes: list[TranslationScope] = Field(default_factory=list)
    tickets: int = 0
    ticket_comments: int = 0
    problems: int = 0
    recommendations: int = 0
    kb_chunks: int = 0
    unique_texts_translated: int = 0


class TranslationDatasetResponse(BaseModel):
    summary: TranslationDatasetSummaryOut
    translation_provider: str
    tickets: list[TicketTranslationOut] = Field(default_factory=list)
    problems: list[ProblemTranslationOut] = Field(default_factory=list)
    recommendations: list[RecommendationTranslationOut] = Field(default_factory=list)
    kb_chunks: list[KBChunkTranslationOut] = Field(default_factory=list)


class TranslationSuggestionRequest(BaseModel):
    suggestions: list[str] = Field(min_length=1, max_length=200)
    dedupe: bool = True

    @field_validator("suggestions", mode="before")
    @classmethod
    def normalize_suggestions(cls, value: list[str]) -> list[str]:
        cleaned = clean_list(value, max_items=200, item_max_length=_MAX_TEXT_LEN)
        return [clean_multiline(item) for item in cleaned if clean_multiline(item)]


class TranslatedSuggestionOut(BaseModel):
    source_text: str
    translations: BilingualTextOut


class TranslationSuggestionResponse(BaseModel):
    translation_provider: str
    count: int
    suggestions: list[TranslatedSuggestionOut]

