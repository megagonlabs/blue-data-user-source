"""REST callers choose neither server paths nor classes (#133, #134).

The routes run against a stand-in UserSource, so what is checked is exactly
what each route hands the library.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from blue_data_user_api.app import app
from blue_data_user_api.source import create_source


@pytest.fixture
def source(tmp_path):
    fake = MagicMock()
    # The store layout is the library's (#165): ask the source the server really builds.
    fake.default_user_props = create_source(tmp_path).default_user_props
    fake.create_user = AsyncMock()
    fake.add_source = AsyncMock()
    app.state.source = fake
    app.state.data_dir = tmp_path
    return fake


@pytest.fixture
def client(source):
    # Not entered as a context manager, so the lifespan (which builds a real
    # UserSource under the configured data directory) does not run.
    return TestClient(app)


# ── POST /databases/{name} ────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [None, {}])
def test_create_puts_every_store_under_the_data_directory(client, source, tmp_path, body):
    resp = client.post("/databases/alice", json=body) if body is not None else client.post("/databases/alice")
    assert resp.status_code == 201

    kwargs = source.create_user.await_args.kwargs
    user_dir = tmp_path / "sources" / "alice"
    for key in ("metadata_source_props", "contact_source_props", "session_source_props"):
        assert Path(kwargs[key]["connection"]["path"]).parent == user_dir
    assert Path(kwargs["kb_source_props"]["connection"]["directory"]) == user_dir
    assert Path(kwargs["registry_props"]["connection"]["path"]) == tmp_path / "registries" / "alice.json"
    assert Path(kwargs["doc_source_props"]["vector_source"]["directory"]) == user_dir / "sessions"


def test_create_does_not_onboard(client, source):
    """Onboarding is an interview on the console; a REST call has nobody to interview (#120)."""
    assert client.post("/databases/alice").status_code == 201
    kwargs = source.create_user.await_args.kwargs
    assert kwargs["onboard"] is False
    assert kwargs["onboard_metadata"] is False


def test_create_defaults_to_openai_embeddings_searched_by_vector(client, source):
    assert client.post("/databases/alice").status_code == 201
    doc_source = source.create_user.await_args.kwargs["doc_source_props"]
    assert (doc_source["embedding_model"], doc_source["search_mode"]) == ("openai", "vector")


def test_create_takes_the_document_search_choice(client, source, tmp_path):
    """Named values only (#173); the store layout stays the server's."""
    body = {"doc_search_mode": "bm25", "doc_embedding_model": "dummy"}
    assert client.post("/databases/alice", json=body).status_code == 201
    doc_source = source.create_user.await_args.kwargs["doc_source_props"]
    assert (doc_source["embedding_model"], doc_source["search_mode"]) == ("dummy", "bm25")
    assert Path(doc_source["vector_source"]["directory"]) == tmp_path / "sources" / "alice" / "sessions"


@pytest.mark.parametrize("body", [
    {"doc_search_mode": "vector", "doc_embedding_model": "dummy"},   # a hash ranks arbitrarily
    {"doc_search_mode": "fuzzy"},
    {"doc_embedding_model": "my.module.Embedder"},                   # a name, never a class
])
def test_create_rejects_a_bad_document_search_choice(client, source, body):
    assert client.post("/databases/alice", json=body).status_code == 422
    source.create_user.assert_not_awaited()


@pytest.mark.parametrize("key", ["registry", "kb_source", "metadata_source", "contact_source",
                                 "session_source", "doc_source"])
def test_create_rejects_store_overrides(client, source, key):
    sys.modules.pop("this", None)
    body = {key: {"_class": "this.Nope", "connection": {"path": "/tmp/elsewhere/settings.json"}}}
    resp = client.post("/databases/mallory", json=body)
    assert resp.status_code == 422
    source.create_user.assert_not_awaited()
    assert "this" not in sys.modules


@pytest.mark.parametrize("name", ["..", ".", "a.b", "-x", "x" * 65, "%2E%2E"])
def test_create_rejects_names_that_are_not_plain_path_segments(client, source, name):
    resp = client.post(f"/databases/{name}")
    assert resp.status_code in (404, 405, 422)  # unroutable or rejected, never created
    source.create_user.assert_not_awaited()


# ── POST /{name}/sources ──────────────────────────────────────────────────────

def test_add_source_ingests_the_documented_free_text(client, source):
    source.add_text_source = AsyncMock(return_value=False)
    text = "Alice joined Acme Corp in 2019 as a data scientist."
    resp = client.post("/alice/sources", json={"source": text, "name": "resume", "queries": ["What role?"]})
    assert resp.status_code == 201
    args, kwargs = source.add_text_source.await_args
    assert args == (text,)
    assert kwargs["database"] == "alice"
    assert kwargs["optional_properties"] == {"name": "resume", "queries": ["What role?"], "location": "rest:resume"}
    source.add_source.assert_not_awaited()  # nothing is read from a path


def test_add_source_never_opens_a_server_path(client, source, tmp_path):
    secret = tmp_path / "unrelated" / "secret.txt"
    secret.parent.mkdir()
    secret.write_text("CANARY-LINE\n")
    source.add_text_source = AsyncMock(return_value=False)

    resp = client.post("/alice/sources", json={"source": str(secret)})
    assert resp.status_code == 201
    assert source.add_text_source.await_args.args == (str(secret),)  # the string itself is the content
    source.add_source.assert_not_awaited()


def test_add_source_records_a_label_not_a_server_path(client, source):
    """#151: the location used to be a deleted temp file under the server's temp directory."""
    source.add_text_source = AsyncMock(return_value=False)
    client.post("/alice/sources", json={"source": "x", "name": "../../etc/passwd"})
    props = source.add_text_source.await_args.kwargs["optional_properties"]
    assert props["location"] == "rest:../../etc/passwd"  # a label, never opened
    client.post("/alice/sources", json={"source": "x"})
    assert "location" not in source.add_text_source.await_args.kwargs["optional_properties"]  # the library's text:<hash>


@pytest.mark.parametrize("value", ["", {"path": "/etc/passwd"}, ["a"]])
def test_add_source_rejects_non_text(client, source, value):
    source.add_text_source = AsyncMock()
    resp = client.post("/alice/sources", json={"source": value})
    assert resp.status_code == 422
    source.add_text_source.assert_not_awaited()


# ── DELETE /{name}/sources/{source_name} (#118) ───────────────────────────────

def test_remove_source_reports_what_it_removed(client, source):
    source.remove_source = AsyncMock(return_value={"id": "s1", "name": "resume", "chunks_removed": 3})
    resp = client.delete("/alice/sources/resume")
    assert resp.status_code == 200
    assert resp.json() == {"database": "alice", "id": "s1", "name": "resume", "chunks_removed": 3}


def test_remove_source_unknown_is_404_not_a_silent_success(client, source):
    from blue_data_user_source import QueryError

    source.remove_source = AsyncMock(side_effect=QueryError("No source 'nope' for user 'alice'."))
    resp = client.delete("/alice/sources/nope")
    assert resp.status_code == 404
    assert "No source 'nope'" in resp.json()["detail"]


# ── LLM failures (#117) ───────────────────────────────────────────────────────

def test_an_llm_failure_is_a_502_not_an_empty_answer(client, source):
    from blue_data_user_source import LLMError

    source.async_execute_query = AsyncMock(side_effect=LLMError("LLM call to 'gpt-4o' failed: connection error"))
    resp = client.post("/alice/query", json={"query": "what are my skills?"})
    assert resp.status_code == 502
    assert "LLM call to 'gpt-4o' failed" in resp.json()["detail"]


# ── contact secrets (#143) ────────────────────────────────────────────────────

def test_contact_reads_mask_secrets(client, source):
    from blue_data_user_source.interaction.contact import ContactMethod

    email = ContactMethod("email", "work", {"address": "a@example.com", "smtp_password": "hunter2"})
    hook = ContactMethod("webhook", "hook", {"url": "https://hooks.example.com/s3cr3t",
                                             "headers": {"Authorization": "Bearer abc"}})
    source.list_contact_methods = AsyncMock(return_value=[email, hook])
    source.get_contact_method = AsyncMock(return_value=email)

    listed = client.get("/alice/contacts").text
    got = client.get("/alice/contacts/email/work").json()

    for secret in ("hunter2", "s3cr3t", "Bearer abc"):
        assert secret not in listed
    assert got["details"] == {"address": "a@example.com", "smtp_password": "***"}


# ── cross-origin writes (#139) ────────────────────────────────────────────────

def test_a_cross_site_post_is_refused(client, source):
    source.reset_user = AsyncMock()
    resp = client.post("/databases/ivy/reset", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    assert "evil.example" in resp.json()["detail"]
    source.reset_user.assert_not_awaited()


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_write_method_checks_the_origin(client, source, method):
    resp = client.request(method, "/databases/ivy", headers={"Origin": "null"})
    assert resp.status_code == 403


def test_same_origin_and_non_browser_writes_still_work(client, source):
    source.reset_user = AsyncMock()
    assert client.post("/databases/ivy/reset").status_code == 200                                  # curl, SDKs
    assert client.post("/databases/ivy/reset", headers={"Origin": "http://testserver"}).status_code == 200  # own page
    assert source.reset_user.await_count == 2


def test_reads_are_not_affected(client, source):
    source.list_users = MagicMock(return_value=[])
    assert client.get("/databases", headers={"Origin": "https://evil.example"}).status_code == 200


def test_an_allowed_origin_can_write(client, source, monkeypatch):
    from blue_data_user_api.config import settings

    monkeypatch.setattr(settings, "allowed_origins", "https://ui.example.com, https://other.example")
    source.reset_user = AsyncMock()
    resp = client.post("/databases/ivy/reset", headers={"Origin": "https://ui.example.com"})
    assert resp.status_code == 200
