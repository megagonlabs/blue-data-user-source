"""A reply reaches the question asked by another process (#197).

The MCP server or the CLI asks; ``blue-userdb-api`` receives the reply, knowing
only the interaction id. Two source objects over one registry file stand for the
two processes: each has its own ``pending_interactions`` entry only where it asked.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from blue_data_user_source import FileUserSource
from blue_data_user_source.interaction import pending
from blue_data_user_source.interaction.contact import ContactMethod
from blue_data_user_source.interaction.pending import (
    ReplyBox,
    deliver_reply,
    is_reply_pending,
    pending_interactions,
)
from blue_data_user_source.types import InteractionTimeoutError

_WEBHOOK = {"url": "http://example.com/hook", "response_base_url": "http://example.com"}


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pending, "REPLY_POLL_SECONDS", 0.01)


def _source(tmp_path: Path) -> FileUserSource:
    return FileUserSource("us", {"connection": {"path": str(tmp_path / "registry.json")}, "console": False})


@pytest.fixture
def asker(tmp_path: Path) -> ReplyBox:
    return _source(tmp_path).replies


@pytest.fixture
def server(tmp_path: Path) -> ReplyBox:
    return _source(tmp_path).replies


def _httpx(on_post: AsyncMock) -> MagicMock:
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = on_post
    return MagicMock(AsyncClient=MagicMock(return_value=client), HTTPError=ConnectionError)


async def _ask(replies: ReplyBox, iid: str, *, timeout: float, on_post: AsyncMock) -> str:
    method = ContactMethod("webhook", "hook", {**_WEBHOOK, "timeout": timeout}, replies=replies)
    with patch.dict(sys.modules, {"httpx": _httpx(on_post)}):
        return await method.interact(interaction_id=iid).send("Where do you live?")


async def test_a_reply_delivered_elsewhere_reaches_the_waiting_question(asker: ReplyBox, server: ReplyBox) -> None:
    iid = str(uuid4())

    async def answered_by_the_other_process(*args, **kwargs) -> MagicMock:
        # What the REST server sees: nothing in its own pending_interactions.
        future = pending_interactions.pop(iid)
        assert is_reply_pending(server, iid)
        assert deliver_reply(server, iid, "Lisbon") == "accepted"
        pending_interactions[iid] = future
        return MagicMock(raise_for_status=MagicMock())

    assert await _ask(asker, iid, timeout=5, on_post=AsyncMock(side_effect=answered_by_the_other_process)) == "Lisbon"
    assert not server.is_pending(iid)  # the record went with the question
    assert server.deliver(iid, "again") == "unknown"


async def test_a_reply_in_the_asking_process_still_wakes_it_at_once(asker: ReplyBox) -> None:
    iid = str(uuid4())

    async def answered_here(*args, **kwargs) -> MagicMock:
        assert deliver_reply(asker, iid, "Porto") == "accepted"
        assert deliver_reply(asker, iid, "again") == "resolved"
        return MagicMock(raise_for_status=MagicMock())

    assert await _ask(asker, iid, timeout=5, on_post=AsyncMock(side_effect=answered_here)) == "Porto"
    assert not asker.is_pending(iid)


async def test_no_reply_times_out_and_leaves_nothing_behind(asker: ReplyBox, server: ReplyBox) -> None:
    iid = str(uuid4())
    delivered = AsyncMock(return_value=MagicMock(raise_for_status=MagicMock()))
    with pytest.raises(InteractionTimeoutError):
        await _ask(asker, iid, timeout=0.05, on_post=delivered)
    assert server.deliver(iid, "too late") == "unknown"


def test_a_second_reply_is_refused(asker: ReplyBox, server: ReplyBox) -> None:
    iid = str(uuid4())
    asker.open(iid, 60)
    assert server.deliver(iid, "first") == "accepted"
    assert server.deliver(iid, "second") == "resolved"
    assert not server.is_pending(iid)
    assert asker.reply(iid) == "first"


def test_a_question_past_its_deadline_is_gone(asker: ReplyBox, server: ReplyBox) -> None:
    """Its asker may have died: a reply must not be told it was accepted."""
    iid = str(uuid4())
    asker.open(iid, -1)
    assert server.deliver(iid, "anyone there?") == "unknown"
    assert not server.is_pending(iid)


@pytest.mark.parametrize("interaction_id", ["abc", "../../source/us", "a.b"])
def test_an_id_that_is_no_interaction_id_is_unknown(server: ReplyBox, interaction_id: str) -> None:
    assert server.deliver(interaction_id, "x") == "unknown"
    assert not server.is_pending(interaction_id)


async def test_a_contact_read_through_the_source_carries_the_box(tmp_path: Path) -> None:
    source = _source(tmp_path)
    source.create_database("alice", {"doc_embedding_model": "dummy", "doc_search_mode": "bm25"})
    await source.add_contact_method("alice", "webhook", "hook", dict(_WEBHOOK))
    assert (await source.get_contact_method("alice", "webhook", "hook")).replies is not None
    [method] = await source.list_contact_methods("alice", "webhook")
    assert method.replies is not None
