"""Unified exception hierarchy for PromiseLink.

Architecture Design §8.0.8 — 7-role review P0 gap fix.
Three categories: BusinessError, LLMError, InfrastructureError.
"""

from typing import Optional


class PromiseLinkError(Exception):
    """Base exception for all PromiseLink errors."""

    def __init__(self, message: str, code: str, details: Optional[dict] = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)


# ── Business Errors ──


class BusinessError(PromiseLinkError):
    """Business logic error base class."""


class NotFoundError(BusinessError):
    """Resource not found."""

    def __init__(self, message: str = "Resource not found", details: Optional[dict] = None):
        super().__init__(
            message=message,
            code="NOT_FOUND",
            details=details or {},
        )


class ValidationError(BusinessError):
    """Request validation / bad input error."""

    def __init__(self, message: str = "Validation error", details: Optional[dict] = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            details=details or {},
        )


class ForbiddenError(BusinessError):
    """Access denied / forbidden error."""

    def __init__(self, message: str = "Forbidden", details: Optional[dict] = None):
        super().__init__(
            message=message,
            code="FORBIDDEN",
            details=details or {},
        )


class UnauthorizedError(BusinessError):
    """Authentication failure error."""

    def __init__(self, message: str = "Unauthorized", details: Optional[dict] = None):
        super().__init__(
            message=message,
            code="UNAUTHORIZED",
            details=details or {},
        )


class ConflictError(BusinessError):
    """Conflict / optimistic lock failure error."""

    def __init__(self, message: str = "Conflict", details: Optional[dict] = None):
        super().__init__(
            message=message,
            code="CONFLICT",
            details=details or {},
        )


class EntityNotFoundError(BusinessError):
    """Entity not found in database."""

    def __init__(self, entity_id: str):
        super().__init__(
            message=f"Entity not found: {entity_id}",
            code="ENTITY_NOT_FOUND",
            details={"entity_id": entity_id},
        )


class InvalidTodoTypeError(BusinessError):
    """Invalid todo_type value."""

    VALID_TYPES = [
        "promise", "help", "care", "followup", "cooperation_signal", "risk"
    ]

    def __init__(self, todo_type: str):
        super().__init__(
            message=f"Invalid todo_type: {todo_type}",
            code="INVALID_TODO_TYPE",
            details={"todo_type": todo_type, "valid_types": self.VALID_TYPES},
        )


class DuplicateEntityError(BusinessError):
    """Entity already exists (resolution conflict)."""

    def __init__(self, entity_id: str, conflict_id: str):
        super().__init__(
            message=f"Entity conflict: {entity_id} vs {conflict_id}",
            code="DUPLICATE_ENTITY",
            details={"entity_id": entity_id, "conflict_id": conflict_id},
        )


class InvalidTransitionError(BusinessError):
    """Invalid todo status transition."""

    def __init__(self, from_status: str, to_status: str):
        super().__init__(
            message=f"Cannot transition from {from_status} to {to_status}",
            code="INVALID_TRANSITION",
            details={"from_status": from_status, "to_status": to_status},
        )


class SensitivityViolationError(BusinessError):
    """Attempted to match a no_match sensitivity resource."""

    def __init__(self, entity_id: str):
        super().__init__(
            message=f"Resource marked as no_match, cannot participate in matching",
            code="SENSITIVITY_VIOLATION",
            details={"entity_id": entity_id},
        )


# ── LLM Errors ──


class LLMError(PromiseLinkError):
    """LLM call base exception."""


class LLMTimeoutError(LLMError):
    """LLM request timeout."""

    def __init__(self, provider: str, timeout: int):
        super().__init__(
            message=f"LLM timeout: {provider} after {timeout}s",
            code="LLM_TIMEOUT",
            details={"provider": provider, "timeout": timeout},
        )


class LLMRateLimitError(LLMError):
    """LLM rate limit exceeded."""

    def __init__(self, provider: str):
        super().__init__(
            message=f"LLM rate limit: {provider}",
            code="LLM_RATE_LIMIT",
            details={"provider": provider},
        )


class LLMQuotaExceeded(LLMError):
    """LLM quota exhausted."""

    def __init__(self, provider: str):
        super().__init__(
            message=f"LLM quota exceeded: {provider}",
            code="LLM_QUOTA_EXCEEDED",
            details={"provider": provider},
        )


class LLMResponseParseError(LLMError):
    """Failed to parse LLM response."""

    def __init__(self, parse_error: str):
        super().__init__(
            message=f"LLM response parse error: {parse_error}",
            code="LLM_PARSE_ERROR",
            details={"parse_error": parse_error},
        )


# ── Infrastructure Errors ──


class InfrastructureError(PromiseLinkError):
    """Infrastructure error base class."""


class DatabaseError(InfrastructureError):
    """Database operation error."""

    def __init__(self, operation: str, original_error: str = ""):
        super().__init__(
            message=f"Database error during {operation}",
            code="DATABASE_ERROR",
            details={"operation": operation, "original_error": original_error},
        )


class CarryMemUnavailableError(InfrastructureError):
    """CarryMem service unavailable."""

    def __init__(self):
        super().__init__(
            message="CarryMem unavailable, using NullMemoryProvider",
            code="CARRYMEM_UNAVAILABLE",
        )
