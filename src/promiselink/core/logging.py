"""Structured logging configuration for PromiseLink.

Architecture Design §8.0.7 — 7-role review P0 gap fix.
Uses structlog for JSON structured output with request_id propagation.
"""

import uuid
from contextvars import ContextVar

import structlog

# Context variables for request-scoped data
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")


def configure_logging(log_level: str = "INFO", json_output: bool = True) -> None:
    """Configure structured logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_output: If True, output JSON format; otherwise console format.
    """
    import logging

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set root logger level
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))


def get_logger(name: str = "promiselink") -> structlog.stdlib.BoundLogger:
    """Get a structured logger with module name binding.

    Args:
        name: Module name for the logger.

    Returns:
        A bound structlog logger instance.
    """
    return structlog.get_logger(name)


def new_request_id() -> str:
    """Generate a new request ID and set it in context.

    Returns:
        The generated request ID.
    """
    req_id = str(uuid.uuid4())
    request_id_var.set(req_id)
    return req_id
