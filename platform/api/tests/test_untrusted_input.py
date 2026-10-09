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


@pytest.fixture
def source(tmp_path):
    fake = MagicMock()
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

def _capture_ingested(source):
    """Record the path add_source was given and the file's text at that moment."""
    seen = {}

    async def _add_source(path, database, optional_properties):
        seen.update(path=path, text=Path(path).read_text(), database=database, props=optional_properties)

    source.add_source.side_effect = _add_source
    return seen


def test_add_source_ingests_the_documented_free_text(client, source):
    seen = _capture_ingested(source)
    text = "Alice joined Acme Corp in 2019 as a data scientist."
    resp = client.post("/alice/sources", json={"source": text, "name": "resume", "queries": ["What role?"]})
    assert resp.status_code == 201
    assert seen["text"] == text
    assert seen["database"] == "alice"
    assert seen["props"] == {"name": "resume", "queries": ["What role?"]}
    assert not Path(seen["path"]).exists()  # the request's own file is cleaned up


def test_add_source_never_opens_a_server_path(client, source, tmp_path):
    secret = tmp_path / "unrelated" / "secret.txt"
    secret.parent.mkdir()
    secret.write_text("CANARY-LINE\n")
    seen = _capture_ingested(source)

    resp = client.post("/alice/sources", json={"source": str(secret)})
    assert resp.status_code == 201
    assert seen["path"] != str(secret)
    assert seen["text"] == str(secret)  # the string itself is the content
    assert "CANARY-LINE" not in seen["text"]


def test_add_source_file_name_cannot_escape_the_temp_directory(client, source):
    seen = _capture_ingested(source)
    resp = client.post("/alice/sources", json={"source": "x", "name": "../../etc/passwd"})
    assert resp.status_code == 201
    assert Path(seen["path"]).name == "______etc_passwd.txt"
    assert seen["props"]["name"] == "../../etc/passwd"  # the label itself is kept


@pytest.mark.parametrize("value", ["", {"path": "/etc/passwd"}, ["a"]])
def test_add_source_rejects_non_text(client, source, value):
    resp = client.post("/alice/sources", json={"source": value})
    assert resp.status_code == 422
    source.add_source.assert_not_awaited()
