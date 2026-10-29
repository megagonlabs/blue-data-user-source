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
_RECIPIENT = f"interaction-{_INTERACTION_ID}@blue-userdb.example.com"
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
    body = _mailgun_body(recipient="unknown@blue-userdb.example.com")
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


# Real Inbound Parse and Mailgun posts are multipart/form-data (#122). Built by
# hand, byte for byte, the way the providers send them.

_BOUNDARY = "xYzZY"
_MULTIPART = f"multipart/form-data; boundary={_BOUNDARY}"


def _part(name: str, value: bytes | str, extra_headers: str = "") -> bytes:
    data = value.encode() if isinstance(value, str) else value
    head = f'--{_BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"{extra_headers}\r\n\r\n'
    return head.encode() + data + b"\r\n"


def _multipart(*parts: bytes) -> bytes:
    return b"".join(parts) + f"--{_BOUNDARY}--\r\n".encode()


def test_sendgrid_reads_a_multipart_payload() -> None:
    body = _multipart(
        _part("headers", "Received: by mx.sendgrid.net\nSubject: Re: A question for you"),
        _part("to", f"Agent <{_RECIPIENT}>"),
        _part("from", "Alice <alice@example.com>"),
        _part("text", f"{_REPLY}\n\nOn Thu, Agent wrote:\n> Which address?"),
        _part("charsets", '{"to":"UTF-8","text":"UTF-8","from":"UTF-8"}'),
    )
    interaction_id, reply = SendgridAdapter().extract(body, _MULTIPART, {})
    assert interaction_id == _INTERACTION_ID
    assert reply == _REPLY


def test_sendgrid_decodes_text_with_the_charset_it_names() -> None:
    body = _multipart(
        _part("to", _RECIPIENT),
        _part("text", "Ja, gerne. Grüße".encode("iso-8859-1")),
        _part("charsets", '{"to":"UTF-8","text":"iso-8859-1"}'),
    )
    _, reply = SendgridAdapter().extract(body, _MULTIPART, {})
    assert reply == "Ja, gerne. Grüße"


def test_sendgrid_skips_attachment_parts() -> None:
    body = _multipart(
        _part("to", _RECIPIENT),
        _part("text", _REPLY),
        _part("attachment1", b"%PDF-1.4 binary\xff\xfe", '; filename="cv.pdf"\r\nContent-Type: application/pdf'),
    )
    interaction_id, reply = SendgridAdapter().extract(body, _MULTIPART, {})
    assert (interaction_id, reply) == (_INTERACTION_ID, _REPLY)


def test_sendgrid_multipart_without_to_still_raises_the_specific_error() -> None:
    body = _multipart(_part("text", _REPLY))
    with pytest.raises(ValueError, match="missing 'to'"):
        SendgridAdapter().extract(body, _MULTIPART, {})


def test_multipart_with_the_wrong_boundary_raises_value_error() -> None:
    body = _multipart(_part("to", _RECIPIENT), _part("text", _REPLY))
    with pytest.raises(ValueError):
        SendgridAdapter().extract(body, "multipart/form-data; boundary=other", {})


def test_mailgun_reads_a_multipart_payload() -> None:
    body = _multipart(
        _part("recipient", _RECIPIENT),
        _part("stripped-text", _REPLY),
        _part("body-plain", f"{_REPLY}\n> quoted"),
        _part("attachment-1", b"\x89PNG", '; filename="a.png"\r\nContent-Type: image/png'),
    )
    assert MailgunAdapter().extract(body, _MULTIPART, {}) == (_INTERACTION_ID, _REPLY)


# ---------------------------------------------------------------------------
# SMTP server stub
# ---------------------------------------------------------------------------

def test_smtp_server_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="smtp_server inbound provider is not yet implemented"):
        SMTPServerAdapter().extract(b"raw email bytes", "message/rfc822", {})


def test_rfc2231_encoded_field_names_are_decoded() -> None:
    """#152: an RFC 2231-encoded name (name*=utf-8''to) must still find 'to'."""
    def encoded(name: str, value: str) -> bytes:
        head = f"--{_BOUNDARY}\r\nContent-Disposition: form-data; name*=utf-8''{name}\r\n\r\n"
        return head.encode() + value.encode() + b"\r\n"

    body = _multipart(encoded("to", _RECIPIENT), encoded("text", _REPLY))
    assert SendgridAdapter().extract(body, _MULTIPART, {}) == (_INTERACTION_ID, _REPLY)


# ---------------------------------------------------------------------------
# Malformed payloads raise ValueError only (#184)
# ---------------------------------------------------------------------------
# The inbound webhook is open (#170): its route answers ValueError with 422, and
# any other exception was a 500.

_JSON, _FORM = "application/json", "application/x-www-form-urlencoded"


@pytest.mark.parametrize(("provider", "body", "content_type"), [
    ("postmark", b"{}", _JSON),                       # no To at all
    ("postmark", b"[1]", _JSON),                      # an array, not an object
    ("postmark", b'{"ToFull": ["x"]}', _JSON),        # a ToFull entry that is not an object
    ("postmark", b'{"ToFull": {"Email": 1}}', _JSON), # ToFull not a list
    ("postmark", b'{"To": 5}', _JSON),                # a numeric To
    ("postmark", b'{"To": "   "}', _JSON),            # a blank To
    ("postmark", f'{{"To": "{_RECIPIENT}", "TextBody": 7}}'.encode(), _JSON),  # a numeric body
    ("mailgun", b"recipient=%20&stripped-text=x", _FORM),  # a whitespace-only recipient
    ("sendgrid", b"to=%20&text=x", _FORM),
])
def test_a_malformed_payload_raises_value_error(provider: str, body: bytes, content_type: str) -> None:
    with pytest.raises(ValueError):
        get_adapter(provider).parse(body, content_type, {})


def test_a_well_formed_postmark_payload_still_parses_through_parse() -> None:
    body = f'{{"ToFull": ["junk", {{"Email": "{_RECIPIENT}"}}], "TextBody": " {_REPLY} "}}'.encode()
    assert get_adapter("postmark").parse(body, _JSON, {}) == (_INTERACTION_ID, _REPLY)


def test_parse_turns_any_other_parsing_error_into_value_error() -> None:
    class Clumsy(MailgunAdapter):
        def extract(self, body, content_type, headers):
            return {}["missing"]

    with pytest.raises(ValueError, match="Malformed Clumsy payload: KeyError"):
        Clumsy().parse(b"", _FORM, {})


@pytest.mark.parametrize("provider", ["mailgun", "postmark", "sendgrid", "smtp_server"])
def test_random_payloads_raise_nothing_but_value_error(provider: str) -> None:
    import json
    import random

    rng = random.Random(184)
    shapes = [None, 0, 1.5, True, "", " ", "x", [], ["x"], [{}], {}, {"Email": 3}, [{"MailboxHash": 2}]]
    adapter = get_adapter(provider)
    for _ in range(300):
        if rng.random() < 0.5:
            body, content_type = bytes(rng.randrange(256) for _ in range(rng.randrange(40))), rng.choice(
                [_JSON, _FORM, "multipart/form-data; boundary=x", ""])
        else:
            obj = {k: rng.choice(shapes) for k in rng.sample(
                ["To", "ToFull", "TextBody", "StrippedTextReply", "recipient", "to", "text"], 3)}
            body, content_type = json.dumps(obj).encode(), _JSON
        try:
            adapter.parse(body, content_type, {})
        except (ValueError, NotImplementedError):
            pass
