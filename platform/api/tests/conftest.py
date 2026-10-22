"""Most tests here are about routes, not authentication: they run with the API key
explicitly disabled. test_security.py turns it back on to check the policy (#157)."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    # A key or flag exported in the developer's shell must not change what tests see.
    monkeypatch.delenv("BLUE_DATA_USER_API_KEY", raising=False)
    monkeypatch.setenv("BLUE_DATA_USER_API_AUTH_DISABLED", "true")
