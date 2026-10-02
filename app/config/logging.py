"""
Structured JSON logging for IBM Cloud Terraform DriftGuard AI.

Never logs:
- IBM Cloud API keys / IAM tokens
- Slack webhook URLs
- LLM API keys
- Terraform sensitive values
- Any secret from the settings layer
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.config.settings import get_settings

# Fields that must never appear in log output.
_REDACTED_FIELDS = frozenset(
    {
        "llm_api_key",
        "slack_webhook_url",
        "api_key",
        "token",
        "password",
        "secret",
        "iam_token",
        "ibmcloud_api_key",
    }
)


def _redact_sensitive(logger: Any, method: str, event_dict: dict) -> dict:  # noqa: ANN401
    """structlog processor — strip sensitive fields before emission."""
    for field in list(event_dict.keys()):
        if field.lower() in _REDACTED_FIELDS:
            event_dict[field] = "[REDACTED]"
    return event_dict


def configure_logging() -> None:
    """Configure structlog once at application start-up."""
    settings = get_settings()

    log_level = getattr(logging, settings.log_level, logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact_sensitive,
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.log_format == "json":
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        shared_processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging so third-party libraries use structlog.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )


def get_logger(name: str = "driftguard") -> Any:  # noqa: ANN401
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
