"""The service follows the family's HTTP policy from blue_data.server (#157, blue-data#116).

An API key is required by default, state-changing requests with a form-style body
are refused, and the server binds to loopback on the family's port for this service.
The reply form an email links to and the inbound-email webhook stay reachable
without a key: a person clicking a link and a mail provider cannot send one.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from blue_data_user_api import app as app_module
from blue_data_user_api.app import app
from blue_data_user_api.source import create_source

KEY = "test-key"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.delenv("BLUE_DATA_USER_API_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("BLUE_DATA_USER_API_KEY", KEY)
    app.state.source = create_source(tmp_path)
    app.state.data_dir = tmp_path
    return TestClient(app, raise_server_exceptions=False)


# ── API key ────────────────────────────────────────────────────────────────────

def test_a_request_without_the_key_is_401(client: TestClient) -> None:
    assert client.get("/databases").status_code == 401
    assert client.post("/databases/alice").status_code == 401


def test_a_wrong_key_is_401(client: TestClient) -> None:
    assert client.get("/databases", headers={"X-API-Key": "nope"}).status_code == 401


@pytest.mark.parametrize("headers", [{"X-API-Key": KEY}, {"Authorization": f"Bearer {KEY}"}])
def test_the_key_is_accepted_either_way(client: TestClient, headers: dict) -> None:
    assert client.get("/databases", headers=headers).status_code == 200


def test_no_key_configured_refuses_rather_than_opens(client: TestClient, monkeypatch) -> None:
    monkeypatch.delenv("BLUE_DATA_USER_API_KEY")
    resp = client.get("/databases")
    assert resp.status_code == 401
    assert "BLUE_DATA_USER_API_AUTH_DISABLED" in resp.json()["detail"]


def test_auth_can_be_disabled_explicitly(client: TestClient, monkeypatch) -> None:
    monkeypatch.delenv("BLUE_DATA_USER_API_KEY")
    monkeypatch.setenv("BLUE_DATA_USER_API_AUTH_DISABLED", "true")
    assert client.get("/databases").status_code == 200


@pytest.mark.parametrize(("method", "path"), [
    ("GET", "/alice/data"),
    ("POST", "/alice/query"),
    ("GET", "/alice/metadata"),
    ("GET", "/alice/contacts"),
    ("GET", "/alice/sessions"),
    ("POST", "/interactions/some-id/response"),
])
def test_every_data_route_requires_the_key(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path, json={}).status_code == 401


def test_health_is_open(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_the_email_reply_routes_need_no_key(client: TestClient) -> None:
    # Unknown interaction ids: the point is that the guard lets them through.
    form = client.get("/interactions/no-such-id/respond")
    assert form.status_code != 401
    inbound = client.post(
        "/interactions/email/inbound", data={"recipient": "reply+no-such-id@example.com", "stripped-text": "hi"},
    )
    assert inbound.status_code not in (401, 415)


# ── CSRF guard ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("content_type", [
    "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", "text/plain",
])
def test_a_form_style_write_is_415(client: TestClient, content_type: str) -> None:
    resp = client.post(
        "/databases/alice", content=b"x=1", headers={"X-API-Key": KEY, "Content-Type": content_type},
    )
    assert resp.status_code == 415


def test_a_json_write_passes(client: TestClient) -> None:
    assert client.post("/databases/alice", json={}, headers={"X-API-Key": KEY}).status_code == 201


# ── bind ───────────────────────────────────────────────────────────────────────

def _bound(monkeypatch, **env: str) -> tuple[str, int]:
    for name in ("BLUE_DATA_USER_API_HOST", "BLUE_DATA_USER_API_PORT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with patch.object(app_module.uvicorn, "run") as run:
        app_module.main()
    return run.call_args.kwargs["host"], run.call_args.kwargs["port"]


def test_the_default_bind_is_loopback_on_8003(monkeypatch) -> None:
    assert _bound(monkeypatch) == ("127.0.0.1", 8003)


def test_host_and_port_come_from_the_family_variables(monkeypatch) -> None:
    assert _bound(monkeypatch, BLUE_DATA_USER_API_HOST="0.0.0.0", BLUE_DATA_USER_API_PORT="9100") == (
        "0.0.0.0", 9100,
    )
