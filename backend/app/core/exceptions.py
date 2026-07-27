"""
Unified exception hierarchy for TopicEye backend.

All custom exceptions inherit from AppException so that FastAPI exception
handlers can catch them uniformly.
"""

from __future__ import annotations

from typing import Any


class AppException(Exception):
    """Base application exception."""

    def __init__(
        self,
        message: str = "An unexpected error occurred",
        status_code: int = 500,
        detail: dict[str, Any] | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(self.message)


# ── Resource errors ──────────────────────────────────────────────────


class NotFoundError(AppException):
    """Requested resource does not exist."""

    def __init__(self, resource: str = "Resource", resource_id: Any = None):
        msg = f"{resource} not found"
        if resource_id is not None:
            msg = f"{resource} (id={resource_id}) not found"
        super().__init__(message=msg, status_code=404)


class AlreadyExistsError(AppException):
    """Resource already exists."""

    def __init__(self, resource: str = "Resource", field: str = "", value: Any = None):
        msg = f"{resource} already exists"
        if field and value is not None:
            msg = f"{resource} with {field}='{value}' already exists"
        super().__init__(message=msg, status_code=409)


# ── Validation errors ────────────────────────────────────────────────


class ValidationError(AppException):
    """Input validation failure."""

    def __init__(self, message: str = "Validation error", detail: dict | None = None):
        super().__init__(message=message, status_code=422, detail=detail)


# ── External service errors ──────────────────────────────────────────


class ExternalServiceError(AppException):
    """Third-party service failure (LLM, scraper, etc.)."""

    def __init__(self, service: str = "external service", message: str = ""):
        msg = f"{service} error: {message}" if message else f"{service} unavailable"
        super().__init__(message=msg, status_code=502)


class LLMApiError(ExternalServiceError):
    """LLM provider API error (rate-limit, auth, timeout, etc.)."""

    def __init__(self, provider: str = "LLM", message: str = ""):
        super().__init__(service=f"LLM ({provider})", message=message)


class RateLimitExceeded(AppException):
    """Rate limit exceeded — client should back off."""

    def __init__(self, retry_after: int | None = None):
        detail = {}
        if retry_after:
            detail["retry_after"] = retry_after
        super().__init__(
            message="Rate limit exceeded",
            status_code=429,
            detail=detail,
        )


# ── Pipeline errors ──────────────────────────────────────────────────


class PipelineError(AppException):
    """Content pipeline processing error."""

    def __init__(self, stage: str = "", message: str = ""):
        msg = f"Pipeline error at '{stage}': {message}" if stage else message
        super().__init__(message=msg, status_code=500)


class AnalysisError(PipelineError):
    """AI analysis failure."""

    def __init__(self, message: str = "", content_id: int | None = None):
        detail = {}
        if content_id:
            detail["content_id"] = content_id
        super().__init__(stage="analysis", message=message)
        self.detail = detail
