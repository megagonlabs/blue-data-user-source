"""REST callers choose neither server paths nor classes (#134).

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
