from dataclasses import dataclass, field
from typing import Any


@dataclass
class QueryResult:
    """One resolved sub-question and its retrieved data."""

    query: str
    results: list[Any] = field(default_factory=list)


class UserDbError(Exception):
    """Base exception for all UserDb errors."""


class QueryError(UserDbError):
    """Raised when a query cannot be processed or no database is available."""


class ImportError(UserDbError):  # noqa: A001
    """Raised when a source import fails."""


class InteractionError(UserDbError):
    """Raised when user interaction fails (channel unavailable, timeout, etc.)."""
