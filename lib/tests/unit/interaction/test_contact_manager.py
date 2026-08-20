"""Tests for ContactMethod and ContactManager."""
from __future__ import annotations

import asyncio
import io
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.interaction.contact import ContactManager, ContactMethod
from blue_data_user_source.interaction.manager import InteractionManager
from blue_data_user_source.interaction.pending import pending_interactions
from blue_data_user_source.types import InteractionError


@pytest.fixture
def contact_manager(manager: UserDataManager, user_id: str) -> ContactManager:
    return ContactManager(database=user_id, data_manager=manager)


# ── ContactMethod ─────────────────────────────────────────────────────────────

def test_contact_method_unsupported_protocol_raises() -> None:
    with pytest.raises(InteractionError, match="Unsupported contact protocol"):
        ContactMethod(protocol="carrier-pigeon", name="x", details={})


def test_contact_method_stdio_interact_returns_interaction_manager() -> None:
    method = ContactMethod(protocol="stdio", name="default", details={})
    assert isinstance(method.interact(), InteractionManager)


def test_contact_method_unimplemented_protocol_interact_raises() -> None:
    # Protocols that are registered but have no manager implementation raise.
    method = ContactMethod(protocol="sms", name="x", details={})
    with pytest.raises(InteractionError, match="requires a registered handler"):
        method.interact()


def test_contact_method_preference_defaults_to_zero() -> None:
    method = ContactMethod(protocol="stdio", name="default", details={})
    assert method.preference == 0


def test_contact_method_preference_from_details() -> None:
    method = ContactMethod(protocol="email", name="work", details={"preference": 3})
    assert method.preference == 3


# ── ContactManager CRUD ───────────────────────────────────────────────────────

async def test_list_contact_methods_empty_for_new_user(contact_manager: ContactManager) -> None:
    methods = await contact_manager.list_contact_methods()
    assert methods == []


async def test_create_and_get_contact_method(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {"address": "alice@example.com"})
    method = await contact_manager.get_contact_method("email", "work")
    assert method is not None
    assert method.protocol == "email"
    assert method.name == "work"
    assert method.details["address"] == "alice@example.com"


async def test_get_missing_contact_method_returns_none(contact_manager: ContactManager) -> None:
    result = await contact_manager.get_contact_method("email", "nonexistent")
    assert result is None


async def test_delete_contact_method(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {"address": "alice@example.com"})
    await contact_manager.delete_contact_method("email", "work")
    assert await contact_manager.get_contact_method("email", "work") is None


async def test_update_contact_method(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {"address": "old@example.com"})
    await contact_manager.update_contact_method("email", "work", address="new@example.com")
    method = await contact_manager.get_contact_method("email", "work")
    assert method is not None
    assert method.details["address"] == "new@example.com"


async def test_update_missing_contact_method_raises(contact_manager: ContactManager) -> None:
    with pytest.raises(InteractionError, match="not found"):
        await contact_manager.update_contact_method("email", "ghost", address="x@y.com")


async def test_create_unsupported_protocol_raises(contact_manager: ContactManager) -> None:
    with pytest.raises(InteractionError, match="Unsupported contact protocol"):
        await contact_manager.create_contact_method("carrier-pigeon", "x", {})


# ── list / filter ─────────────────────────────────────────────────────────────

async def test_list_contact_methods_returns_created_entry(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {"address": "a@b.com"})
    methods = await contact_manager.list_contact_methods()
    assert any(m.protocol == "email" and m.name == "work" for m in methods)


async def test_list_contact_methods_filtered_by_protocol(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {})
    await contact_manager.create_contact_method("sms", "mobile", {"number": "+1555"})
    methods = await contact_manager.list_contact_methods(protocol="email")
    assert len(methods) == 1
    assert methods[0].protocol == "email"


async def test_list_protocols(contact_manager: ContactManager) -> None:
    protocols = await contact_manager.list_protocols()
    # contact schema seeds all protocol buckets
    assert "email" in protocols
    assert "sms" in protocols


async def test_list_named_entries(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {"address": "a@b.com"})
    await contact_manager.create_contact_method("email", "home", {"address": "h@b.com"})
    entries = await contact_manager.list_named_entries("email")
    assert "work" in entries
    assert "home" in entries


# ── identify_contact_method ───────────────────────────────────────────────────

async def test_identify_returns_stdio_when_no_methods(contact_manager: ContactManager) -> None:
    method = await contact_manager.identify_contact_method()
    assert method.protocol == "stdio"


async def test_identify_picks_lowest_preference(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {}, preference=5)
    await contact_manager.create_contact_method("sms", "mobile", {}, preference=1)
    method = await contact_manager.identify_contact_method()
    assert method.protocol == "sms"
    assert method.preference == 1


# ── stdio interaction ─────────────────────────────────────────────────────────

async def test_stdio_send_writes_prompt_and_reads_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_out = io.StringIO()
    fake_in = io.StringIO("yes, remote\n")
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stdin", fake_in)

    method = ContactMethod(protocol="stdio", name="default", details={})
    mgr = method.interact()
    response = await mgr.send("Do you prefer remote work?")

    assert response == "yes, remote"
    assert "Do you prefer remote work?" in fake_out.getvalue()


async def test_stdio_send_strips_trailing_newline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stdin", io.StringIO("answer\n"))

    mgr = ContactMethod(protocol="stdio", name="default", details={}).interact()
    assert not (await mgr.send("q?")).endswith("\n")


# ── webhook interaction ───────────────────────────────────────────────────────

def test_contact_method_webhook_interact_returns_interaction_manager() -> None:
    method = ContactMethod(
        protocol="webhook",
        name="bot",
        details={"url": "http://example.com/hook", "response_base_url": "http://localhost:8000"},
    )
    assert isinstance(method.interact(), InteractionManager)


def _make_mock_httpx(on_post=None):
    """Build a mock httpx module whose AsyncClient resolves futures via on_post."""
    import sys

    async def _default_post(url, *, json, headers, timeout):
        pass

    post_fn = on_post or _default_post

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = post_fn

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient = MagicMock(return_value=mock_client)
    return mock_httpx


async def test_webhook_sends_post_and_resolves_future() -> None:
    import sys

    async def _post_and_resolve(url, *, json, headers, timeout):
        for fut in list(pending_interactions.values()):
            if not fut.done():
                fut.set_result("yes, remote")

    method = ContactMethod(
        protocol="webhook",
        name="bot",
        details={"url": "http://example.com/hook", "response_base_url": "http://localhost:8000"},
    )
    mgr = method.interact()

    with patch.dict(sys.modules, {"httpx": _make_mock_httpx(_post_and_resolve)}):
        response = await mgr.send("Do you prefer remote work?")

    assert response == "yes, remote"


async def test_webhook_timeout_raises_interaction_error() -> None:
    import sys

    method = ContactMethod(
        protocol="webhook",
        name="bot",
        details={
            "url": "http://example.com/hook",
            "response_base_url": "http://localhost:8000",
            "timeout": 0.01,
        },
    )
    mgr = method.interact()

    with patch.dict(sys.modules, {"httpx": _make_mock_httpx()}):
        with pytest.raises(InteractionError, match="No response received"):
            await mgr.send("Will this time out?")


# ── email interaction ─────────────────────────────────────────────────────────

_EMAIL_DETAILS = {
    "address": "alice@example.com",
    "from_address": "agent@udb.example.com",
    "smtp_host": "smtp.example.com",
    "reply_domain": "udb.example.com",
    "response_base_url": "http://localhost:8000",
}


def _mock_aiosmtplib(send_fn=None) -> MagicMock:
    """Build a mock aiosmtplib module whose send() calls send_fn."""
    mock = MagicMock()
    mock.send = AsyncMock(side_effect=send_fn) if send_fn else AsyncMock()
    return mock


def test_contact_method_email_interact_returns_interaction_manager() -> None:
    method = ContactMethod(protocol="email", name="work", details=_EMAIL_DETAILS)
    assert isinstance(method.interact(), InteractionManager)


async def test_email_sends_message_and_resolves_future() -> None:
    import sys

    async def _send_and_resolve(msg, *, hostname, port, username, password, start_tls):
        for fut in list(pending_interactions.values()):
            if not fut.done():
                fut.set_result("I prefer async.")

    with patch.dict(sys.modules, {"aiosmtplib": _mock_aiosmtplib(_send_and_resolve)}):
        method = ContactMethod(protocol="email", name="work", details=_EMAIL_DETAILS)
        response = await method.interact().send("Do you prefer sync or async Python?")

    assert response == "I prefer async."


async def test_email_includes_reply_to_and_link() -> None:
    import sys

    sent_msgs: list = []

    async def _capture(msg, *, hostname, port, username, password, start_tls):
        sent_msgs.append(msg)
        for fut in list(pending_interactions.values()):
            if not fut.done():
                fut.set_result("ok")

    with patch.dict(sys.modules, {"aiosmtplib": _mock_aiosmtplib(_capture)}):
        method = ContactMethod(protocol="email", name="work", details=_EMAIL_DETAILS)
        await method.interact().send("Pick a colour.")

    assert sent_msgs, "aiosmtplib.send was not called"
    msg = sent_msgs[0]
    reply_to = msg.get("Reply-To", "")
    assert reply_to.startswith("interaction-")
    assert "udb.example.com" in reply_to
    body = msg.as_string()
    assert "/interactions/" in body
    assert "/respond" in body


async def test_email_timeout_raises_interaction_error() -> None:
    import sys

    details = {**_EMAIL_DETAILS, "timeout": 0.01}
    with patch.dict(sys.modules, {"aiosmtplib": _mock_aiosmtplib()}):
        method = ContactMethod(protocol="email", name="work", details=details)
        with pytest.raises(InteractionError, match="No email response"):
            await method.interact().send("Will this time out?")


# ── email stdio provider ──────────────────────────────────────────────────────

_EMAIL_STDIO_DETAILS = {
    "address": "alice@example.com",
    "from_address": "agent@udb.example.com",
    "reply_domain": "udb.example.com",
    "subject": "A question for you",
    "inbound_provider": "stdio",
}


def test_email_stdio_interact_returns_interaction_manager() -> None:
    method = ContactMethod(protocol="email", name="work", details=_EMAIL_STDIO_DETAILS)
    assert isinstance(method.interact(), InteractionManager)


async def test_email_stdio_writes_formatted_email_and_reads_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_out = io.StringIO()
    fake_in = io.StringIO("I prefer the home address.\n")
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stdin", fake_in)

    method = ContactMethod(protocol="email", name="work", details=_EMAIL_STDIO_DETAILS)
    response = await method.interact().send("Which delivery address should I use?")

    assert response == "I prefer the home address."

    output = fake_out.getvalue()
    assert "alice@example.com" in output       # To:
    assert "agent@udb.example.com" in output    # From:
    assert "A question for you" in output       # Subject:
    assert "interaction-" in output             # Reply-To:
    assert "udb.example.com" in output          # reply domain
    assert "Which delivery address" in output   # message body


async def test_email_stdio_does_not_require_smtp_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Minimal details — only address required; no smtp_host or response_base_url."""
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stdin", io.StringIO("ok\n"))

    method = ContactMethod(
        protocol="email",
        name="work",
        details={"address": "alice@example.com", "inbound_provider": "stdio"},
    )
    response = await method.interact().send("Test question?")
    assert response == "ok"


async def test_email_stdio_strips_trailing_newline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stdin", io.StringIO("answer\n"))

    method = ContactMethod(protocol="email", name="work", details=_EMAIL_STDIO_DETAILS)
    response = await method.interact().send("q?")
    assert not response.endswith("\n")
