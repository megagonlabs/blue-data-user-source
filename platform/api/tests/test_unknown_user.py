"""A route that names an unknown user answers 404, not 500 (#145)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from blue_data_user_api.app import app
from blue_data_user_api.source import create_source


@pytest.fixture
def client(tmp_path):
    app.state.source = create_source(tmp_path)
    app.state.data_dir = tmp_path
    # Not entered as a context manager, so the lifespan does not replace the source.
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(("method", "path", "body"), [
    ("DELETE", "/databases/nobody", None),
    ("POST", "/databases/nobody/reset", None),
    ("POST", "/nobody/query", {"query": "what are my skills?"}),
    ("GET", "/nobody/data", None),
    ("GET", "/nobody/sources", None),
    ("DELETE", "/nobody/sources/resume", None),
    ("GET", "/nobody/metadata", None),
    ("GET", "/nobody/sessions", None),
    ("POST", "/nobody/sessions", None),
    ("GET", "/nobody/contacts", None),
])
def test_unknown_user_is_404(client, method, path, body):
    resp = client.request(method, path, json=body)
    assert resp.status_code == 404, resp.text
    assert "nobody" in resp.json()["detail"]


def test_creating_an_existing_user_is_409_and_keeps_its_data(client):
    """#141: the second POST used to return 201 and orphan the user's metadata."""
    assert client.post("/databases/ana").status_code == 201
    assert client.put("/ana/metadata/identity.timezone", json={"value": "Asia/Tokyo"}).status_code == 200

    again = client.post("/databases/ana")
    assert again.status_code == 409
    assert "already exists" in again.json()["detail"]
    assert client.get("/ana/metadata/identity.timezone").json()["value"] == "Asia/Tokyo"


# ── library errors are client errors, not 500s (#140) ─────────────────────────

def test_session_and_contact_errors_map_to_client_statuses(client):
    assert client.post("/databases/bo").status_code == 201

    unknown = client.post("/bo/query", json={"query": "where?", "session": "no-such-session"})
    assert unknown.status_code == 404 and "no-such-session" in unknown.json()["detail"]
    assert client.post("/bo/sessions/no-such-session/end").status_code == 404

    sid = client.post("/bo/sessions").json()["session_id"]
    assert client.post(f"/bo/sessions/{sid}/end").status_code == 200
    ended = client.post("/bo/query", json={"query": "where?", "session": sid})
    assert ended.status_code == 409 and "has ended" in ended.json()["detail"]

    bad = client.post("/bo/contacts", json={"protocol": "carrier-pigeon", "name": "x", "details": {}})
    assert bad.status_code == 422 and "Unsupported contact protocol" in bad.json()["detail"]
    missing = client.patch("/bo/contacts/email/nope", json={"preference": 1})
    assert missing.status_code == 404 and "not found" in missing.json()["detail"]


@pytest.mark.parametrize(("method", "path"), [
    ("POST", "/ana/contacts"), ("PATCH", "/ana/contacts/webhook/hook"),
])
def test_a_contact_referencing_a_server_variable_is_422(client, method, path):
    """#198: the variable would be sent to the contact's own target."""
    assert client.post("/databases/ana").status_code == 201
    details = {"url": "http://example.com/hook", "response_base_url": "http://example.com"}
    assert client.post("/ana/contacts", json={"protocol": "webhook", "name": "hook",
                                              "details": details}).status_code == 201
    body = {"details": {**details, "headers": {"X-Demo": "$OPENAI_API_KEY"}}}
    if method == "POST":
        body |= {"protocol": "webhook", "name": "other"}
    resp = client.request(method, path, json=body)
    assert resp.status_code == 422, resp.text
    assert "BLUE_DATA_USER_CONTACT_" in resp.json()["detail"]
    assert client.get("/ana/contacts/webhook/hook").json()["details"].get("headers") is None


def test_nameless_sources_with_different_text_are_both_kept(client):
    """#196: both answered 201, and the second had silently replaced the first."""
    assert client.post("/databases/ana", json={"doc_search_mode": "bm25",
                                               "doc_embedding_model": "dummy"}).status_code == 201
    for text in ("Ana speaks fluent Japanese.", "Ana keeps bees in Lisbon."):
        resp = client.post("/ana/sources", json={"source": text})
        assert resp.status_code == 201 and resp.json()["updated"] is False
    assert len(client.get("/ana/sources").json()["sources"]) == 2


def test_a_named_source_posted_again_says_it_was_updated(client):
    assert client.post("/databases/ana", json={"doc_search_mode": "bm25",
                                               "doc_embedding_model": "dummy"}).status_code == 201
    assert client.post("/ana/sources", json={"source": "One.", "name": "note"}).status_code == 201
    resp = client.post("/ana/sources", json={"source": "Two.", "name": "note"})
    assert resp.status_code == 200 and resp.json()["updated"] is True
    assert len(client.get("/ana/sources").json()["sources"]) == 1


def test_a_reply_to_a_question_asked_by_another_process_is_accepted(client, tmp_path):
    """#197: the question lives in the shared registry, not in this process."""
    from uuid import uuid4

    other_process = create_source(tmp_path)
    iid = str(uuid4())
    other_process.replies.open(iid, 60)
    assert client.get(f"/interactions/{iid}/respond").status_code == 200
    assert client.post(f"/interactions/{iid}/response", json={"text": "Lisbon"}).status_code == 200
    assert other_process.replies.reply(iid) == "Lisbon"
    assert client.post(f"/interactions/{iid}/response", json={"text": "Porto"}).status_code == 409
    assert client.get(f"/interactions/{iid}/respond").status_code == 404


def test_a_reply_to_nothing_is_404(client):
    assert client.post("/interactions/nothing/response", json={"text": "x"}).status_code == 404


def test_a_contact_with_a_malformed_field_is_422(client):
    """#202."""
    assert client.post("/databases/ana").status_code == 201
    resp = client.post("/ana/contacts", json={"protocol": "webhook", "name": "hook", "details": {"timeout": "soon"}})
    assert resp.status_code == 422 and "timeout" in resp.json()["detail"]


def test_listing_contacts_by_an_unknown_protocol_is_422(client):
    """#203: it was a KeyError, so a 500."""
    assert client.post("/databases/ana").status_code == 201
    assert client.get("/ana/contacts?protocol=webhook").status_code == 200
    resp = client.get("/ana/contacts?protocol=pigeon")
    assert resp.status_code == 422 and "pigeon" in resp.json()["detail"]

