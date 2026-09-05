"""Tests for UserSource's onboard-on-create wiring (#41)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from blue_data_user_source.data.manager import CLS_JSON_MEMORY, CLS_KB_MEMORY
from blue_data_user_source.memory_user_source import MemoryUserSource
from blue_data_user_source.source import _DEFAULT_METADATA_SCHEMA_PATH

_MEM_JSON = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}


def _create_user_kwargs(**overrides) -> dict:
    kwargs = {
        "registry_props": _MEM_JSON,
        "kb_source_props": _MEM_KB,
        "metadata_source_props": _MEM_JSON,
        "contact_source_props": _MEM_JSON,
        "session_source_props": _MEM_JSON,
    }
    kwargs.update(overrides)
    return kwargs


async def test_create_user_onboards_by_default() -> None:
    source = MemoryUserSource()
    with patch(
        "blue_data_user_source.source.UserQueryReasoner.onboard", AsyncMock()
    ) as mock_onboard:
        await source.create_user("alice", **_create_user_kwargs())
    mock_onboard.assert_awaited_once_with(metadata_schema_path=_DEFAULT_METADATA_SCHEMA_PATH)


async def test_create_user_skips_onboarding_when_disabled() -> None:
    source = MemoryUserSource()
    with patch(
        "blue_data_user_source.source.UserQueryReasoner.onboard", AsyncMock()
    ) as mock_onboard:
        await source.create_user("alice", **_create_user_kwargs(onboard=False))
    mock_onboard.assert_not_awaited()


async def test_onboard_user_can_be_called_standalone() -> None:
    source = MemoryUserSource()
    with patch(
        "blue_data_user_source.source.UserQueryReasoner.onboard", AsyncMock()
    ) as mock_onboard:
        await source.create_user("alice", **_create_user_kwargs(onboard=False))
        mock_onboard.assert_not_awaited()

        await source.onboard_user("alice")
    mock_onboard.assert_awaited_once_with(metadata_schema_path=_DEFAULT_METADATA_SCHEMA_PATH)
