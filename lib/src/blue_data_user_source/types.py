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


class ImportError(UDbError):  # noqa: A001
    """Raised when a source import fails."""


class InteractionError(UDbError):
    """Raised when user interaction fails (channel unavailable, timeout, etc.)."""


class NoContactMethodError(InteractionError):
    """Raised when no contact method can reach the user from this process."""
