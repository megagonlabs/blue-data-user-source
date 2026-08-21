"""Tests for SessionManager."""
from __future__ import annotations

import pytest

from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.interaction.session import SessionManager
from blue_data_user_source.types import InteractionError


@pytest.fixture
def session_manager(manager: UserDataManager, user_id: str) -> SessionManager:
    return SessionManager(database=user_id, data_manager=manager)


# ── sessions ─────────────────────────────────────────────────────────────────

async def test_create_session_returns_active_record(session_manager: SessionManager) -> None:
    session_id = await session_manager.create_session()
    record = await session_manager.get_session(session_id)
    assert record is not None
    assert record["status"] == "active"
    assert record["ended_at"] is None
    assert record["queries"] == {}


async def test_get_session_returns_none_for_unknown(session_manager: SessionManager) -> None:
    assert await session_manager.get_session("nonexistent") is None


async def test_list_sessions_includes_created_session(session_manager: SessionManager) -> None:
    session_id = await session_manager.create_session()
    sessions = await session_manager.list_sessions()
    assert session_id in sessions


async def test_end_session_sets_status_and_timestamp(session_manager: SessionManager) -> None:
    session_id = await session_manager.create_session()
    await session_manager.end_session(session_id)
    record = await session_manager.get_session(session_id)
    assert record is not None
    assert record["status"] == "ended"
    assert record["ended_at"] is not None


async def test_end_session_unknown_raises(session_manager: SessionManager) -> None:
    with pytest.raises(InteractionError, match="not found"):
        await session_manager.end_session("nonexistent")


# ── queries ──────────────────────────────────────────────────────────────────

async def test_create_query_appears_under_session(session_manager: SessionManager) -> None:
    session_id = await session_manager.create_session()
    query_id = await session_manager.create_query(session_id, "what is my favorite color?")
    record = await session_manager.get_session(session_id)
    assert record is not None
    assert query_id in record["queries"]
    assert record["queries"][query_id]["query"] == "what is my favorite color?"
    assert record["queries"][query_id]["interactions"] == {}


async def test_create_query_unknown_session_raises(session_manager: SessionManager) -> None:
    with pytest.raises(InteractionError, match="not found"):
        await session_manager.create_query("nonexistent", "q?")


async def test_create_query_on_ended_session_raises(session_manager: SessionManager) -> None:
    session_id = await session_manager.create_session()
    await session_manager.end_session(session_id)
    with pytest.raises(InteractionError, match="has ended"):
        await session_manager.create_query(session_id, "q?")


# ── interactions ─────────────────────────────────────────────────────────────

async def test_create_interaction_is_pending(session_manager: SessionManager) -> None:
    session_id = await session_manager.create_session()
    query_id = await session_manager.create_query(session_id, "q?")
    interaction_id = await session_manager.create_interaction(
        session_id, query_id, "Could you clarify?", "stdio", "default"
    )
    record = await session_manager.get_session(session_id)
    assert record is not None
    interaction = record["queries"][query_id]["interactions"][interaction_id]
    assert interaction["status"] == "pending"
    assert interaction["question"] == "Could you clarify?"
    assert interaction["contact"] == {"protocol": "stdio", "name": "default"}
    assert interaction["response"] is None


async def test_resolve_interaction_stores_response(session_manager: SessionManager) -> None:
    session_id = await session_manager.create_session()
    query_id = await session_manager.create_query(session_id, "q?")
    interaction_id = await session_manager.create_interaction(
        session_id, query_id, "Could you clarify?", "stdio", "default"
    )
    await session_manager.resolve_interaction(session_id, query_id, interaction_id, "sure, blue")

    record = await session_manager.get_session(session_id)
    assert record is not None
    interaction = record["queries"][query_id]["interactions"][interaction_id]
    assert interaction["status"] == "resolved"
    assert interaction["response"] == "sure, blue"
    assert interaction["resolved_at"] is not None


async def test_resolve_interaction_ingests_transcript_into_session_doc_source(
    session_manager: SessionManager, manager: UserDataManager
) -> None:
    session_id = await session_manager.create_session()
    query_id = await session_manager.create_query(session_id, "q?")
    interaction_id = await session_manager.create_interaction(
        session_id, query_id, "Could you clarify?", "stdio", "default"
    )
    await session_manager.resolve_interaction(session_id, query_id, interaction_id, "sure, blue")

    doc_source = manager.ensure_session_doc_source(session_id)
    chunks = list(doc_source._pipeline._chunk_index.values())
    assert any("sure, blue" in c.get("text", "") for c in chunks)
    # Cached per-process — resolving a second interaction reuses the same instance.
    assert manager.ensure_session_doc_source(session_id) is doc_source


async def test_mark_interaction_timeout_sets_status(session_manager: SessionManager) -> None:
    session_id = await session_manager.create_session()
    query_id = await session_manager.create_query(session_id, "q?")
    interaction_id = await session_manager.create_interaction(
        session_id, query_id, "Could you clarify?", "webhook", "bot"
    )
    await session_manager.mark_interaction_timeout(session_id, query_id, interaction_id)

    record = await session_manager.get_session(session_id)
    assert record is not None
    interaction = record["queries"][query_id]["interactions"][interaction_id]
    assert interaction["status"] == "timeout"
    assert interaction["resolved_at"] is not None
