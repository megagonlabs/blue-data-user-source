"""Lightweight stubs used across the test suite."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock


def make_mock_kb(result: list[Any] | str | None = None, metadata: dict | None = None) -> Any:
    """Return a mock KBSource whose answer() resolves to (result, metadata)."""
    kb = AsyncMock()
    kb.answer = AsyncMock(return_value=(result if result is not None else [], metadata or {}))
    kb.import_text = AsyncMock()
    return kb
