"""Tests for core exceptions module."""

import pytest

from promiselink.core.exceptions import (
    BusinessError,
    CarryMemUnavailableError,
    DatabaseError,
    DuplicateEntityError,
    EntityNotFoundError,
    PromiseLinkError,
    InfrastructureError,
    InvalidTodoTypeError,
    InvalidTransitionError,
    LLMError,
    LLMQuotaExceeded,
    LLMRateLimitError,
    LLMResponseParseError,
    LLMTimeoutError,
    SensitivityViolationError,
)


class TestExceptionHierarchy:
    """Verify exception class hierarchy is correct."""

    def test_base_error_is_exception(self):
        assert issubclass(PromiseLinkError, Exception)

    def test_business_error_inherits_base(self):
        assert issubclass(BusinessError, PromiseLinkError)

    def test_llm_error_inherits_base(self):
        assert issubclass(LLMError, PromiseLinkError)

    def test_infrastructure_error_inherits_base(self):
        assert issubclass(InfrastructureError, PromiseLinkError)

    def test_entity_not_found_is_business(self):
        assert issubclass(EntityNotFoundError, BusinessError)

    def test_invalid_todo_type_is_business(self):
        assert issubclass(InvalidTodoTypeError, BusinessError)

    def test_duplicate_entity_is_business(self):
        assert issubclass(DuplicateEntityError, BusinessError)

    def test_invalid_transition_is_business(self):
        assert issubclass(InvalidTransitionError, BusinessError)

    def test_sensitivity_violation_is_business(self):
        assert issubclass(SensitivityViolationError, BusinessError)

    def test_llm_timeout_is_llm(self):
        assert issubclass(LLMTimeoutError, LLMError)

    def test_llm_rate_limit_is_llm(self):
        assert issubclass(LLMRateLimitError, LLMError)

    def test_llm_quota_is_llm(self):
        assert issubclass(LLMQuotaExceeded, LLMError)

    def test_llm_parse_error_is_llm(self):
        assert issubclass(LLMResponseParseError, LLMError)

    def test_database_error_is_infrastructure(self):
        assert issubclass(DatabaseError, InfrastructureError)

    def test_carrymem_unavailable_is_infrastructure(self):
        assert issubclass(CarryMemUnavailableError, InfrastructureError)


class TestExceptionDetails:
    """Verify exception details are correctly set."""

    def test_entity_not_found_details(self):
        exc = EntityNotFoundError("ent_123")
        assert exc.code == "ENTITY_NOT_FOUND"
        assert exc.details["entity_id"] == "ent_123"
        assert "ent_123" in exc.message

    def test_invalid_todo_type_details(self):
        exc = InvalidTodoTypeError("unknown")
        assert exc.code == "INVALID_TODO_TYPE"
        assert exc.details["todo_type"] == "unknown"
        assert len(exc.details["valid_types"]) == 6
        assert "promise" in exc.details["valid_types"]

    def test_invalid_transition_details(self):
        exc = InvalidTransitionError("done", "pending")
        assert exc.code == "INVALID_TRANSITION"
        assert exc.details["from_status"] == "done"
        assert exc.details["to_status"] == "pending"

    def test_llm_timeout_details(self):
        exc = LLMTimeoutError("openai", 30)
        assert exc.code == "LLM_TIMEOUT"
        assert exc.details["provider"] == "openai"
        assert exc.details["timeout"] == 30

    def test_llm_parse_error_no_pii(self):
        """LLM parse error must NOT store raw response (PII risk)."""
        exc = LLMResponseParseError("invalid json")
        assert exc.code == "LLM_PARSE_ERROR"
        assert "raw_response" not in exc.details

    def test_catch_by_base_class(self):
        """All specific errors can be caught by PromiseLinkError."""
        with pytest.raises(PromiseLinkError):
            raise EntityNotFoundError("x")
        with pytest.raises(PromiseLinkError):
            raise LLMTimeoutError("p", 10)
        with pytest.raises(PromiseLinkError):
            raise DatabaseError("select")
