"""Lightweight stubs used across the test suite."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock


def make_mock_kb(result: list[Any] | str | None = None, metadata: dict | None = None) -> Any:
    """Return a mock KBSource whose answer() resolves to (result, metadata)."""
    kb = AsyncMock()
    kb.answer = AsyncMock(return_value=(result if result is not None else [], metadata or {}))
    kb.import_text = AsyncMock()
    kb.add_source = AsyncMock(return_value="source-1")  # KBSource returns the new SOURCE node's id
    kb.match_nodes = MagicMock(return_value=[])  # synchronous on KBSource; no SOURCE nodes yet
    return kb
