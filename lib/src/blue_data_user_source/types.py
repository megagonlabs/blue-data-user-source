from dataclasses import dataclass, field
from typing import Any


@dataclass
class QueryResult:
    """One resolved sub-question and its retrieved data."""

    query: str
    results: list[Any] = field(default_factory=list)


class UDbError(Exception):
    """Base exception for all UDb errors."""


class QueryError(UDbError):
    """Raised when a query cannot be processed or no database is available."""


class UserNotFoundError(QueryError):
    """Raised when an operation names a user (database) that is not registered."""


class ImportError(UDbError):  # noqa: A001
    """Raised when a source import fails."""


class LLMError(UDbError):
    """Raised when the language model cannot be reached or returns an unusable reply.

    Covers authentication, network, rate-limit, timeout and unknown-model errors
    from the OpenAI SDK, a missing ``openai`` package, and a JSON-mode reply that
    is not a JSON object. Callers must not turn it into an empty result: an
    outage would then look like a user with no data (#117).
    """


class InteractionError(UDbError):
    """Raised when user interaction fails (channel unavailable, timeout, etc.)."""


class InteractionTimeoutError(InteractionError):
    """Raised when the user did not answer within the contact method's timeout."""


class NoContactMethodError(InteractionError):
    """Raised when no contact method can reach the user from this process."""
