"""The open email-reply routes answer malformed input with a 4xx, never a 500 (#183, #184).

Both are reachable without the API key by design (#170), so their input is anyone's.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from blue_data_user_api.app import app
from blue_data_user_api.source import create_source

_JSON, _FORM = "application/json", "application/x-www-form-urlencoded"


@pytest.fixture
def client(tmp_path) -> TestClient:
    app.state.source = create_source(tmp_path)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(("provider", "body", "content_type"), [
    ("postmark", b"{}", _JSON),
    ("postmark", b"[1]", _JSON),
    ("postmark", b'{"ToFull": ["x"]}', _JSON),
    ("postmark", b'{"To": 5}', _JSON),
    ("mailgun", b"stripped-text=x", _FORM),
    ("mailgun", b"recipient=%20&stripped-text=x", _FORM),
])
def test_a_malformed_inbound_email_is_answered_422(client, provider, body, content_type) -> None:
    resp = client.post(f"/interactions/email/inbound?provider={provider}", content=body,
                       headers={"Content-Type": content_type})
    assert resp.status_code == 422


def test_a_file_part_for_the_reply_text_is_answered_400(client) -> None:
    resp = client.post("/interactions/abc/respond", files={"text": ("a.txt", b"hello")})
    assert resp.status_code == 400
    assert "Please enter a response" in resp.text


def test_a_reply_typed_in_the_form_still_reaches_the_interaction_check(client) -> None:
    # No interaction "abc" is pending, so a real reply is answered 409, as before.
    assert client.post("/interactions/abc/respond", data={"text": "hello"}).status_code == 409
