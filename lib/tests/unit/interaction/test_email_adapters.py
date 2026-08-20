"""Tests for inbound email adapters (Mailgun, Postmark, Sendgrid, SMTP stub)."""
from __future__ import annotations

from urllib.parse import urlencode

import pytest

from blue_data_user_source.interaction.email.adapter import get_adapter, supported_providers
from blue_data_user_source.interaction.email.mailgun import MailgunAdapter
from blue_data_user_source.interaction.email.postmark import PostmarkAdapter
from blue_data_user_source.interaction.email.sendgrid import SendgridAdapter
from blue_data_user_source.interaction.email.smtp_server import SMTPServerAdapter

_INTERACTION_ID = "abc123-def456"
_RECIPIENT = f"interaction-{_INTERACTION_ID}@udb.example.com"
_REPLY = "I prefer the home address."


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_supported_providers_includes_all() -> None:
    providers = supported_providers()
    assert "mailgun" in providers
    assert "postmark" in providers
    assert "sendgrid" in providers
    assert "smtp_server" in providers


def test_get_adapter_returns_correct_type() -> None:
    assert isinstance(get_adapter("mailgun"), MailgunAdapter)
    assert isinstance(get_adapter("postmark"), PostmarkAdapter)
    assert isinstance(get_adapter("sendgrid"), SendgridAdapter)


def test_get_adapter_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown inbound email provider"):
        get_adapter("carrier-pigeon")


# ---------------------------------------------------------------------------
# Shared helper: _id_from_address
# ---------------------------------------------------------------------------

def test_id_from_address_extracts_id() -> None:
    adapter = MailgunAdapter()
    assert adapter._id_from_address(_RECIPIENT) == _INTERACTION_ID


def test_id_from_address_missing_prefix_raises() -> None:
    adapter = MailgunAdapter()
    with pytest.raises(ValueError, match="does not carry an interaction id"):
        adapter._id_from_address("no-prefix@example.com")


def test_first_address_strips_angle_brackets() -> None:
    adapter = MailgunAdapter()
    assert adapter._first_address("Agent <interaction-x@d.com>") == "interaction-x@d.com"


def test_first_address_picks_first_from_comma_list() -> None:
    adapter = MailgunAdapter()
    assert adapter._first_address("a@b.com, c@d.com") == "a@b.com"


# ---------------------------------------------------------------------------
# Mailgun
# ---------------------------------------------------------------------------

def _mailgun_body(**overrides) -> bytes:
    fields = {
        "recipient": _RECIPIENT,
        "stripped-text": _REPLY,
        "body-plain": f"{_REPLY}\n\nOn Thu, Alice wrote:\n> question text",
        **overrides,
    }
    return urlencode(fields).encode()


def test_mailgun_extracts_id_and_reply() -> None:
    body = _mailgun_body()
    interaction_id, reply = MailgunAdapter().extract(body, "application/x-www-form-urlencoded", {})
    assert interaction_id == _INTERACTION_ID
    assert reply == _REPLY


def test_mailgun_falls_back_to_body_plain_when_stripped_empty() -> None:
    body = _mailgun_body(**{"stripped-text": "", "body-plain": "plain text reply"})
    _, reply = MailgunAdapter().extract(body, "application/x-www-form-urlencoded", {})
    assert reply == "plain text reply"


def test_mailgun_missing_recipient_raises() -> None:
    body = urlencode({"stripped-text": _REPLY}).encode()
    with pytest.raises(ValueError, match="missing 'recipient'"):
        MailgunAdapter().extract(body, "application/x-www-form-urlencoded", {})


def test_mailgun_missing_text_raises() -> None:
    body = urlencode({"recipient": _RECIPIENT}).encode()
    with pytest.raises(ValueError, match="no reply text"):
        MailgunAdapter().extract(body, "application/x-www-form-urlencoded", {})


def test_mailgun_bad_recipient_prefix_raises() -> None:
    body = _mailgun_body(recipient="unknown@udb.example.com")
    with pytest.raises(ValueError, match="does not carry an interaction id"):
        MailgunAdapter().extract(body, "application/x-www-form-urlencoded", {})


# ---------------------------------------------------------------------------
# Postmark
# ---------------------------------------------------------------------------

import json as _json


def _postmark_body(**overrides) -> bytes:
    payload = {
        "ToFull": [{"Email": _RECIPIENT, "Name": "", "MailboxHash": f"interaction-{_INTERACTION_ID}"}],
        "To": _RECIPIENT,
        "StrippedTextReply": _REPLY,
        "TextBody": f"{_REPLY}\n\nOn Thu, Alice wrote:\n> question",
        **overrides,
    }
    return _json.dumps(payload).encode()


def test_postmark_extracts_id_and_stripped_reply() -> None:
    body = _postmark_body()
    interaction_id, reply = PostmarkAdapter().extract(body, "application/json", {})
    assert interaction_id == _INTERACTION_ID
    assert reply == _REPLY


def test_postmark_falls_back_to_text_body_when_stripped_empty() -> None:
    body = _postmark_body(StrippedTextReply="", TextBody="full text")
    _, reply = PostmarkAdapter().extract(body, "application/json", {})
    assert reply == "full text"


def test_postmark_extracts_id_from_email_field_when_no_mailbox_hash() -> None:
    payload = {
        "ToFull": [{"Email": _RECIPIENT, "Name": "", "MailboxHash": ""}],
        "StrippedTextReply": _REPLY,
    }
    body = _json.dumps(payload).encode()
    interaction_id, _ = PostmarkAdapter().extract(body, "application/json", {})
    assert interaction_id == _INTERACTION_ID


def test_postmark_falls_back_to_raw_to_field() -> None:
    payload = {"ToFull": [], "To": _RECIPIENT, "StrippedTextReply": _REPLY}
    body = _json.dumps(payload).encode()
    interaction_id, _ = PostmarkAdapter().extract(body, "application/json", {})
    assert interaction_id == _INTERACTION_ID


def test_postmark_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        PostmarkAdapter().extract(b"not json", "application/json", {})


def test_postmark_no_interaction_id_raises() -> None:
    payload = {"ToFull": [], "To": "noid@example.com", "StrippedTextReply": _REPLY}
    with pytest.raises(ValueError, match="could not extract interaction id"):
        PostmarkAdapter().extract(_json.dumps(payload).encode(), "application/json", {})


def test_postmark_empty_reply_raises() -> None:
    payload = {"ToFull": [{"Email": _RECIPIENT, "MailboxHash": ""}], "StrippedTextReply": "", "TextBody": ""}
    with pytest.raises(ValueError, match="no reply text"):
        PostmarkAdapter().extract(_json.dumps(payload).encode(), "application/json", {})


# ---------------------------------------------------------------------------
# Sendgrid
# ---------------------------------------------------------------------------

def _sendgrid_body(**overrides) -> bytes:
    fields = {
        "to": _RECIPIENT,
        "text": _REPLY,
        **overrides,
    }
    return urlencode(fields).encode()


def test_sendgrid_extracts_id_and_reply() -> None:
    body = _sendgrid_body()
    interaction_id, reply = SendgridAdapter().extract(body, "application/x-www-form-urlencoded", {})
    assert interaction_id == _INTERACTION_ID
    assert reply == _REPLY


def test_sendgrid_strips_quoted_content() -> None:
    raw = f"{_REPLY}\n\nOn Thu, Alice wrote:\n> old question text"
    body = _sendgrid_body(text=raw)
    _, reply = SendgridAdapter().extract(body, "application/x-www-form-urlencoded", {})
    assert reply == _REPLY
    assert "wrote:" not in reply


def test_sendgrid_strips_angle_bracket_quotes() -> None:
    raw = f"{_REPLY}\n> quoted line\n> another"
    body = _sendgrid_body(text=raw)
    _, reply = SendgridAdapter().extract(body, "application/x-www-form-urlencoded", {})
    assert reply == _REPLY


def test_sendgrid_missing_to_raises() -> None:
    body = urlencode({"text": _REPLY}).encode()
    with pytest.raises(ValueError, match="missing 'to'"):
        SendgridAdapter().extract(body, "application/x-www-form-urlencoded", {})


def test_sendgrid_missing_text_raises() -> None:
    body = urlencode({"to": _RECIPIENT}).encode()
    with pytest.raises(ValueError, match="no plain-text body"):
        SendgridAdapter().extract(body, "application/x-www-form-urlencoded", {})


def test_sendgrid_empty_after_stripping_raises() -> None:
    # If the entire body is a quoted block, stripping leaves nothing.
    body = _sendgrid_body(text="> everything is quoted\n> even this")
    with pytest.raises(ValueError, match="empty after stripping"):
        SendgridAdapter().extract(body, "application/x-www-form-urlencoded", {})


# ---------------------------------------------------------------------------
# SMTP server stub
# ---------------------------------------------------------------------------

def test_smtp_server_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="smtp_server inbound provider is not yet implemented"):
        SMTPServerAdapter().extract(b"raw email bytes", "message/rfc822", {})
