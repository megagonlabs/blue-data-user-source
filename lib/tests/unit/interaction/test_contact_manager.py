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
from blue_data_user_source.types import InteractionError, LLMError


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
    with pytest.raises(InteractionError, match="no built-in transport"):
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
    await contact_manager.create_contact_method("webhook", "mobile", {}, preference=1)
    # Simulate an LLM failure (LLMError, #117) so the deterministic
    # lowest-preference fallback is what's under test, not a live model call.
    with patch(
        "blue_data_user_source.reasoning.reasoner._llm_complete",
        new=AsyncMock(side_effect=LLMError("down")),
    ):
        method = await contact_manager.identify_contact_method()
    assert method.protocol == "webhook"
    assert method.preference == 1


async def test_identify_skips_llm_when_only_one_method(
    contact_manager: ContactManager,
) -> None:
    await contact_manager.create_contact_method("email", "work", {}, preference=5)
    with patch(
        "blue_data_user_source.reasoning.reasoner._llm_complete", new=AsyncMock()
    ) as mock_llm:
        method = await contact_manager.identify_contact_method()
    assert method.protocol == "email"
    mock_llm.assert_not_called()


async def test_identify_uses_llm_choice_among_multiple_methods(
    contact_manager: ContactManager,
) -> None:
    await contact_manager.create_contact_method("email", "work", {}, preference=1)
    await contact_manager.create_contact_method("webhook", "mobile", {}, preference=5)
    mock_llm = AsyncMock(return_value={"protocol": "webhook", "name": "mobile"})
    with patch(
        "blue_data_user_source.reasoning.reasoner._llm_complete", new=mock_llm
    ):
        method = await contact_manager.identify_contact_method()
    assert method.protocol == "webhook"
    assert method.name == "mobile"
    mock_llm.assert_awaited_once()


async def test_identify_falls_back_when_llm_choice_is_invalid(
    contact_manager: ContactManager,
) -> None:
    await contact_manager.create_contact_method("email", "work", {}, preference=1)
    await contact_manager.create_contact_method("webhook", "mobile", {}, preference=5)
    mock_llm = AsyncMock(return_value={"protocol": "webhook", "name": "nonexistent"})
    with patch(
        "blue_data_user_source.reasoning.reasoner._llm_complete", new=mock_llm
    ):
        method = await contact_manager.identify_contact_method()
    assert method.protocol == "email"
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


class _FakeHTTPError(Exception):
    """Stands in for httpx.HTTPError in the mocked module."""


def _make_mock_httpx(on_post=None):
    """Build a mock httpx module whose AsyncClient resolves futures via on_post."""
    import sys

    async def _default_post(url, *, json, headers, timeout):
        pass

    post_fn = on_post or _default_post

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    async def _post(*args, **kwargs):
        # Like httpx: post() returns a response that raise_for_status() checks.
        result = await post_fn(*args, **kwargs)
        return result if result is not None else MagicMock(raise_for_status=MagicMock())

    mock_client.post = _post

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient = MagicMock(return_value=mock_client)
    mock_httpx.HTTPError = _FakeHTTPError
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
    "from_address": "agent@blue-userdb.example.com",
    "smtp_host": "smtp.example.com",
    "reply_domain": "blue-userdb.example.com",
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
    assert "blue-userdb.example.com" in reply_to
    body = msg.as_string()
    assert "/interactions/" in body
    assert "/respond" in body


async def test_email_html_body_escapes_the_question() -> None:
    sent_msgs: list = []

    async def _capture(msg, *, hostname, port, username, password, start_tls):
        sent_msgs.append(msg)
        for fut in list(pending_interactions.values()):
            if not fut.done():
                fut.set_result("ok")

    question = 'Is this your manager, Jane Doe <jane@corp.com>?\n<a href="https://evil.example">Verify</a> &copy'
    with patch.dict(sys.modules, {"aiosmtplib": _mock_aiosmtplib(_capture)}):
        method = ContactMethod(protocol="email", name="work", details=_EMAIL_DETAILS)
        await method.interact().send(question)

    parts = {p.get_content_type(): p.get_payload(decode=True).decode() for p in sent_msgs[0].get_payload()}
    html_body = parts["text/html"]
    assert "Jane Doe &lt;jane@corp.com&gt;?<br>" in html_body
    assert '&lt;a href=&quot;https://evil.example&quot;&gt;' in html_body
    assert "&amp;copy" in html_body
    assert "evil.example\">" not in html_body
    assert question in parts["text/plain"]


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
    "from_address": "agent@blue-userdb.example.com",
    "reply_domain": "blue-userdb.example.com",
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
    assert "agent@blue-userdb.example.com" in output    # From:
    assert "A question for you" in output       # Subject:
    assert "interaction-" in output             # Reply-To:
    assert "blue-userdb.example.com" in output          # reply domain
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


# ── recorded-only protocols (#129) ────────────────────────────────────────────

@pytest.mark.parametrize("protocol", ["sms", "messaging", "enterprise", "notification", "session"])
def test_recorded_only_protocols_have_no_transport(protocol: str) -> None:
    assert not ContactMethod(protocol=protocol, name="x", details={}).has_transport


@pytest.mark.parametrize("protocol", ["stdio", "email", "webhook"])
def test_transport_protocols(protocol: str) -> None:
    assert ContactMethod(protocol=protocol, name="x", details={}).has_transport


async def test_a_recorded_only_method_is_never_chosen(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("sms", "phone", {"number": "+15550100"}, preference=0)
    await contact_manager.create_contact_method("email", "work", {"address": "a@example.com"}, preference=5)
    channel = await contact_manager.identify_contact_method()  # one usable candidate: no LLM choice
    assert (channel.protocol, channel.name) == ("email", "work")


async def test_only_recorded_methods_falls_back_like_none_registered(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("sms", "phone", {"number": "+15550100"})
    channel = await contact_manager.identify_contact_method()
    assert (channel.protocol, channel.name) == ("stdio", "default")


# ── secrets in contact details (#143) ─────────────────────────────────────────

from blue_data_user_source.interaction.contact import (  # noqa: E402
    MASK, SECRET_FIELDS, redact_contacts, redact_details, resolve_secret,
)


def test_the_schema_marks_the_credential_fields_secret() -> None:
    assert SECRET_FIELDS["email"] == {"smtp_password"}
    assert SECRET_FIELDS["webhook"] == {"url", "headers"}
    assert SECRET_FIELDS["notification"] == {"endpoint"}


def test_redact_details_masks_secrets_and_keeps_everything_else() -> None:
    details = {"address": "a@example.com", "smtp_password": "hunter2", "preference": 1}
    assert redact_details("email", details) == {"address": "a@example.com", "smtp_password": MASK, "preference": 1}
    assert details["smtp_password"] == "hunter2"  # the stored dict is untouched


def test_redact_details_masks_each_header_and_the_webhook_url() -> None:
    details = {"url": "https://hooks.example.com/T0/B0/xyz", "headers": {"Authorization": "Bearer abc", "X-Env": "prod"}}
    assert redact_details("webhook", details) == {"url": MASK, "headers": {"Authorization": MASK, "X-Env": MASK}}


def test_a_var_reference_is_shown_because_it_holds_no_secret() -> None:
    details = {"smtp_password": "$SMTP_PASSWORD", "address": "a@example.com"}
    assert redact_details("email", details)["smtp_password"] == "$SMTP_PASSWORD"


def test_redact_contacts_covers_the_whole_tree() -> None:
    tree = {"email": {"work": {"smtp_password": "p"}}, "stdio": {"default": {}}}
    assert redact_contacts(tree) == {"email": {"work": {"smtp_password": MASK}}, "stdio": {"default": {}}}


def test_contact_method_public_dict_is_masked() -> None:
    method = ContactMethod(protocol="email", name="work", details={"address": "a@example.com", "smtp_password": "p"})
    assert method.public_dict() == {"protocol": "email", "name": "work",
                                    "details": {"address": "a@example.com", "smtp_password": MASK}}


def test_resolve_secret_reads_the_environment_at_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOK_TOKEN", "Bearer real")
    assert resolve_secret("$HOOK_TOKEN") == "Bearer real"
    assert resolve_secret({"Authorization": "$HOOK_TOKEN", "X": "y"}) == {"Authorization": "Bearer real", "X": "y"}
    assert resolve_secret("plain") == "plain"
    monkeypatch.delenv("HOOK_TOKEN")
    with pytest.raises(InteractionError, match=r"\$HOOK_TOKEN"):
        resolve_secret("$HOOK_TOKEN")


async def test_email_sends_with_the_password_from_the_referenced_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_PASSWORD", "from-env")
    seen: dict = {}

    async def _capture(msg, *, hostname, port, username, password, start_tls):
        seen["password"] = password
        for fut in list(pending_interactions.values()):
            if not fut.done():
                fut.set_result("ok")

    with patch.dict(sys.modules, {"aiosmtplib": _mock_aiosmtplib(_capture)}):
        method = ContactMethod(protocol="email", name="work", details={**_EMAIL_DETAILS, "smtp_password": "$SMTP_PASSWORD"})
        await method.interact().send("Pick a colour.")
    assert seen["password"] == "from-env"


# ── updating details (#137) ───────────────────────────────────────────────────

async def test_updating_details_replaces_the_stored_fields(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {"address": "old@example.com", "subject": "Hi"}, preference=2)
    await contact_manager.update_contact_method("email", "work", details={"address": "new@example.com"})

    method = await contact_manager.get_contact_method("email", "work")
    assert method.details == {"address": "new@example.com", "preference": 2}
    chosen = await contact_manager.identify_contact_method()  # the only usable method
    assert chosen.details["address"] == "new@example.com"


async def test_updating_details_and_preference_together(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {"address": "a@example.com"}, preference=2)
    await contact_manager.update_contact_method("email", "work", details={"address": "b@example.com"}, preference=0)
    assert (await contact_manager.get_contact_method("email", "work")).details == {"address": "b@example.com", "preference": 0}


async def test_writing_back_a_masked_read_keeps_the_secrets(contact_manager: ContactManager) -> None:
    """A client that reads a contact (secrets masked, #143) and writes it back must not store '***'."""
    await contact_manager.create_contact_method(
        "webhook", "hook", {"url": "https://hooks.example.com/s3cr3t", "response_base_url": "http://x",
                            "headers": {"Authorization": "Bearer abc", "X-Env": "prod"}})
    read = (await contact_manager.get_contact_method("webhook", "hook")).public_dict()["details"]
    read["headers"]["X-Env"] = "staging"            # one header edited, the secret one left masked
    read.pop("preference")
    await contact_manager.update_contact_method("webhook", "hook", details=read)

    stored = (await contact_manager.get_contact_method("webhook", "hook")).details
    assert stored["url"] == "https://hooks.example.com/s3cr3t"
    assert stored["headers"] == {"Authorization": "Bearer abc", "X-Env": "staging"}


async def test_a_masked_single_field_update_is_ignored(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {"address": "a@example.com", "smtp_password": "p"})
    await contact_manager.update_contact_method("email", "work", smtp_password="***", address="c@example.com")
    stored = (await contact_manager.get_contact_method("email", "work")).details
    assert stored["smtp_password"] == "p" and stored["address"] == "c@example.com"
