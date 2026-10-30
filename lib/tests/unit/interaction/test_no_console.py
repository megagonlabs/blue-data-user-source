"""Without a console, nothing asks the user on stdin/stdout (#132, #120).

Servers construct their UserSource with ``console=False``: their stdin/stdout
belong to the server (for the MCP stdio transport, stdout is the protocol
stream), so clarification and onboarding must never use them.
"""
from __future__ import annotations

import asyncio
import io
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blue_data_user_source import MemoryUserSource
from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.interaction.contact import ContactManager, ContactMethod
from blue_data_user_source.reasoning.metric import MetricEvaluation
from blue_data_user_source.reasoning.reasoner import UserQueryReasoner
from blue_data_user_source.types import NoContactMethodError

_FAILING = [MetricEvaluation(name="completeness", score=0.0, reasoning="", passes=False)]
_EMAIL = {"address": "alice@example.com", "from_address": "agent@example.com",
          "smtp_host": "smtp.example.com", "reply_domain": "example.com",
          "response_base_url": "http://localhost:8000"}


class _ExplodingStdin:
    def readline(self) -> str:
        raise AssertionError("read the console without one")


# ── ContactMethod.uses_console ────────────────────────────────────────────────

@pytest.mark.parametrize(("protocol", "details", "expected"), [
    ("stdio", {}, True),
    ("email", {"address": "a@example.com", "inbound_provider": "stdio"}, True),
    ("email", _EMAIL, False),
    ("webhook", {"url": "http://example.com"}, False),
])
def test_uses_console(protocol, details, expected) -> None:
    assert ContactMethod(protocol=protocol, name="x", details=details).uses_console is expected


# ── ContactManager.identify_contact_method ────────────────────────────────────

async def test_with_a_console_no_methods_still_falls_back_to_stdio(manager: UserDataManager, user_id: str) -> None:
    channel = await ContactManager(user_id, manager).identify_contact_method()
    assert (channel.protocol, channel.name) == ("stdio", "default")


async def test_without_a_console_no_methods_means_no_channel(manager: UserDataManager, user_id: str) -> None:
    assert await ContactManager(user_id, manager, console=False).identify_contact_method() is None


async def test_without_a_console_console_methods_are_never_picked(manager: UserDataManager, user_id: str) -> None:
    cm = ContactManager(user_id, manager, console=False)
    await cm.create_contact_method("stdio", "terminal", {})
    await cm.create_contact_method("email", "dev", {"address": "a@example.com", "inbound_provider": "stdio"})
    assert await cm.identify_contact_method() is None


async def test_without_a_console_a_remote_method_is_still_used(manager: UserDataManager, user_id: str) -> None:
    cm = ContactManager(user_id, manager, console=False)
    await cm.create_contact_method("stdio", "terminal", {})
    await cm.create_contact_method("email", "work", _EMAIL)
    channel = await cm.identify_contact_method()  # one candidate left: no LLM choice needed
    assert (channel.protocol, channel.name) == ("email", "work")


# ── clarification ─────────────────────────────────────────────────────────────

async def test_request_user_interaction_raises_when_nobody_can_be_asked(manager: UserDataManager) -> None:
    reasoner = UserQueryReasoner(source=MagicMock(console=False), manager=manager)
    with pytest.raises(NoContactMethodError):
        await reasoner.request_user_interaction("where?", [], {}, _FAILING)


async def test_failed_checks_without_a_console_return_the_results_without_asking(
    manager: UserDataManager, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "stdin", _ExplodingStdin())
    reasoner = UserQueryReasoner(source=MagicMock(console=False), manager=manager)
    reasoner.assess_query_results = AsyncMock(return_value=_FAILING)  # type: ignore[method-assign]

    new_items = await reasoner.resolve_via_interaction("where?", "where?", ["Berlin"], {}, max_rounds=3)

    assert new_items == []
    assert reasoner.assess_query_results.await_count == 1  # no re-assessment rounds
    assert capsys.readouterr().out == ""


async def test_metric_scores_are_logged_not_printed(
    manager: UserDataManager, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture,
) -> None:
    reasoner = UserQueryReasoner(source=MagicMock(console=False), manager=manager)
    with caplog.at_level("DEBUG", logger="blue_data_user_source"):
        await reasoner.assess_user_interaction("where?", [], {}, _FAILING)
    assert capsys.readouterr().out == ""
    assert "Metric completeness: score=0.0, passes=False" in caplog.text


# ── onboarding ────────────────────────────────────────────────────────────────

async def test_onboarding_without_a_console_asks_nothing_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "stdin", _ExplodingStdin())
    us = MemoryUserSource("no-console", {"console": False})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(return_value={})):
        await us.create_user(
            "dana", registry_props={"backend": "memory"}, kb_source_props={"backend": "memory"},
            metadata_source_props={"backend": "memory"}, contact_source_props={"backend": "memory"},
            session_source_props={"backend": "memory"},
        )  # onboards by default, and identity.name is unset, so the name question is due
    assert us.get_metadata("dana", "identity.name") is None
    assert not await us.list_sessions("dana")
    assert capsys.readouterr().out == ""


def test_console_is_not_stored_in_the_registry() -> None:
    us = MemoryUserSource("no-console", {"console": False})
    assert us.console is False
    assert "console" not in us._registry.get_source_record("no-console")["properties"]


@pytest.mark.parametrize("tty", [True, False])
def test_console_defaults_to_a_terminal(monkeypatch: pytest.MonkeyPatch, tty: bool) -> None:
    """Unset, ``console`` is whether stdin and stdout are terminals (#186)."""
    for name in ("stdin", "stdout"):
        stream = io.StringIO()
        stream.isatty = lambda: tty  # type: ignore[method-assign]
        monkeypatch.setattr(sys, name, stream)
    assert MemoryUserSource("with-console").console is tty


# ── the stdio handler ─────────────────────────────────────────────────────────

class _SlowStdin(io.StringIO):
    def readline(self, *args) -> str:  # type: ignore[override]
        time.sleep(0.3)
        return super().readline(*args)


async def test_stdio_read_does_not_block_the_event_loop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "stdin", _SlowStdin("answer\n"))
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    task = asyncio.create_task(ticker())
    response = await ContactMethod("stdio", "default", {}).interact().send("question?")
    task.cancel()

    assert response == "answer"
    assert ticks >= 5  # the loop kept running while the read waited
