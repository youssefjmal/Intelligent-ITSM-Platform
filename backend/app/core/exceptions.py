"""Custom exceptions for application-specific error handling."""

from __future__ import annotations

from typing import Optional, Dict, Any


class ITSMGatekeeperException(Exception):
    """Base exception for all application errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 400,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.status_code = status_code
        self.headers = headers
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "error_code": self.error_code,
            "details": self.details,
        }


class NotFoundError(ITSMGatekeeperException):
    """Raised when a requested resource is not found."""

    def __init__(self, message: str = "not_found", *, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="NOT_FOUND", details=details, status_code=404)


class ConflictError(ITSMGatekeeperException):
    """Raised when a request conflicts with current state."""

    def __init__(self, message: str = "conflict", *, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="CONFLICT", details=details, status_code=409)


class BadRequestError(ITSMGatekeeperException):
    """Raised when request is invalid."""

    def __init__(self, message: str = "bad_request", *, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="BAD_REQUEST", details=details, status_code=400)


class RateLimitExceeded(ITSMGatekeeperException):
    """Raised when a client exceeds rate limits."""

    def __init__(self, *, retry_after: int, limit: int, window_seconds: int):
        headers = {
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Window": str(window_seconds),
        }
        super().__init__(
            "rate_limit_exceeded",
            error_code="RATE_LIMIT",
            details={"retry_after": retry_after, "limit": limit, "window_seconds": window_seconds},
            status_code=429,
            headers=headers,
        )


# ===== JIRA EXCEPTIONS =====


class JiraException(ITSMGatekeeperException):
    """Base exception for Jira-related errors."""


class JiraConnectionError(JiraException):
    """Raised when cannot connect to Jira."""

    def __init__(self, message: str = "Failed to connect to Jira"):
        super().__init__(message, error_code="JIRA_CONNECTION_ERROR", status_code=502)


class JiraAuthenticationError(JiraException):
    """Raised when Jira authentication fails."""

    def __init__(self, message: str = "Jira authentication failed"):
        super().__init__(message, error_code="JIRA_AUTH_ERROR", status_code=502)


class JiraTicketNotFoundError(JiraException):
    """Raised when ticket doesn't exist."""

    def __init__(self, ticket_key: str):
        super().__init__(
            f"Ticket {ticket_key} not found",
            error_code="JIRA_TICKET_NOT_FOUND",
            details={"ticket_key": ticket_key},
            status_code=404,
        )


class JiraPermissionError(JiraException):
    """Raised when user lacks permission."""

    def __init__(self, message: str = "Insufficient permissions for this operation"):
        super().__init__(message, error_code="JIRA_PERMISSION_ERROR", status_code=403)


class JiraValidationError(JiraException):
    """Raised when Jira data validation fails."""

    def __init__(self, message: str, field: Optional[str] = None):
        details = {"field": field} if field else {}
        super().__init__(message, error_code="JIRA_VALIDATION_ERROR", details=details, status_code=422)


# ===== AI EXCEPTIONS =====


class AIException(ITSMGatekeeperException):
    """Base exception for AI-related errors."""


class OpenAIException(AIException):
    """Raised for OpenAI API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        details = {"status_code": status_code} if status_code else {}
        super().__init__(message, error_code="OPENAI_ERROR", details=details, status_code=502)


class OpenAIRateLimitError(OpenAIException):
    """Raised when hitting OpenAI rate limits."""

    def __init__(self, message: str = "OpenAI rate limit exceeded"):
        super().__init__(message, status_code=429)
        self.error_code = "OPENAI_RATE_LIMIT"


class OpenAITimeoutError(OpenAIException):
    """Raised when OpenAI request times out."""

    def __init__(self, message: str = "OpenAI request timed out"):
        super().__init__(message, status_code=504)
        self.error_code = "OPENAI_TIMEOUT"


class AIConfidenceTooLowError(AIException):
    """Raised when AI confidence is below threshold."""

    def __init__(self, confidence: float, threshold: float):
        super().__init__(
            f"AI confidence {confidence:.2f} is below threshold {threshold:.2f}",
            error_code="AI_LOW_CONFIDENCE",
            details={"confidence": confidence, "threshold": threshold},
            status_code=422,
        )


class AIResponseParsingError(AIException):
    """Raised when cannot parse AI response."""

    def __init__(self, message: str = "Failed to parse AI response"):
        super().__init__(message, error_code="AI_PARSING_ERROR", status_code=502)


# ===== N8N EXCEPTIONS =====


class N8NException(ITSMGatekeeperException):
    """Base exception for n8n-related errors."""


class N8NWebhookError(N8NException):
    """Raised when webhook call fails."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        details = {"status_code": status_code} if status_code else {}
        super().__init__(message, error_code="N8N_WEBHOOK_ERROR", details=details, status_code=502)


class N8NTimeoutError(N8NException):
    """Raised when n8n request times out."""

    def __init__(self, message: str = "n8n request timed out"):
        super().__init__(message, error_code="N8N_TIMEOUT", status_code=504)


# ===== CACHE EXCEPTIONS =====


class CacheException(ITSMGatekeeperException):
    """Base exception for cache-related errors."""


class CacheConnectionError(CacheException):
    """Raised when cannot connect to cache."""

    def __init__(self, message: str = "Failed to connect to cache"):
        super().__init__(message, error_code="CACHE_CONNECTION_ERROR", status_code=503)


class CacheKeyError(CacheException):
    """Raised when cache key operation fails."""

    def __init__(self, key: str, operation: str):
        super().__init__(
            f"Cache {operation} failed for key: {key}",
            error_code="CACHE_KEY_ERROR",
            details={"key": key, "operation": operation},
            status_code=400,
        )


# ===== VALIDATION EXCEPTIONS =====


class ValidationException(ITSMGatekeeperException):
    """Base exception for validation errors."""


class InvalidTicketDataError(ValidationException):
    """Raised when ticket data is invalid."""

    def __init__(self, message: str, field: Optional[str] = None):
        details = {"field": field} if field else {}
        super().__init__(message, error_code="INVALID_TICKET_DATA", details=details, status_code=422)


class InvalidConfigurationError(ValidationException):
    """Raised when configuration is invalid."""

    def __init__(self, message: str, setting: Optional[str] = None):
        details = {"setting": setting} if setting else {}
        super().__init__(message, error_code="INVALID_CONFIG", details=details, status_code=500)


# ===== DATABASE EXCEPTIONS =====


class DatabaseException(ITSMGatekeeperException):
    """Base exception for database errors."""


class DatabaseConnectionError(DatabaseException):
    """Raised when cannot connect to database."""

    def __init__(self, message: str = "Failed to connect to database"):
        super().__init__(message, error_code="DB_CONNECTION_ERROR", status_code=503)


class DatabaseQueryError(DatabaseException):
    """Raised when database query fails."""

    def __init__(self, message: str, query: Optional[str] = None):
        details = {"query": query} if query else {}
        super().__init__(message, error_code="DB_QUERY_ERROR", details=details, status_code=500)


# ===== AUTHENTICATION/AUTHORIZATION EXCEPTIONS =====


class AuthenticationException(ITSMGatekeeperException):
    """Base exception for authentication errors."""


class InvalidAPIKeyError(AuthenticationException):
    """Raised when API key is invalid."""

    def __init__(self, message: str = "Invalid API key"):
        super().__init__(message, error_code="INVALID_API_KEY", status_code=401)


class ExpiredTokenError(AuthenticationException):
    """Raised when token has expired."""

    def __init__(self, message: str = "Token has expired"):
        super().__init__(message, error_code="EXPIRED_TOKEN", status_code=401)


class InsufficientPermissionsError(AuthenticationException):
    """Raised when user lacks required permissions."""

    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message, error_code="INSUFFICIENT_PERMISSIONS", status_code=403)
