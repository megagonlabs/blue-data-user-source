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
