"""Shared fixtures for the `blue-userdb` CLI tests.

Isolation lives here rather than in a single test module because profiles are
read from the CLI home *before* any option is applied: `--data-dir` alone does
not cover them, and without this the suite writes into the developer's own
~/.blue-userdb.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

# Anything in the real ~/.blue-userdb newer than this was written by the test run.
_SESSION_START = time.time()

# Every environment variable that can steer the CLI at a real home directory.
# Listed explicitly so that adding one without isolating it trips the guard
# below rather than silently writing into the developer's own ~/.blue-userdb.
_HOME_ENV_VARS = (
    "BLUE_DATA_USER_SOURCE_HOME",
    "BLUE_DATA_USER_SOURCE_DATA_DIR",
)


class IsolatedRunner(CliRunner):
    """A CliRunner that gives each invocation its own environment.

    The CLI applies a profile by exporting resolved values into `os.environ`,
    which is correct for a real run — one process per command, gone when it
    exits. In-process, those exports would leak into the next `invoke` and make
    the profile tier look like the environment tier.
    """

    def invoke(self, *args, **kwargs):
        saved = dict(os.environ)
        try:
            return super().invoke(*args, **kwargs)
        finally:
            os.environ.clear()
            os.environ.update(saved)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "blue-userdb"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(autouse=True)
def isolated_home(data_dir, monkeypatch):
    """Point profiles and data at tmp_path, and fail loudly if one escapes.

    `--data-dir` alone is not enough: profiles are read from the CLI home
    before any option is applied, so without this the suite writes into the
    developer's real ~/.blue-userdb. The guard is the part that matters — it turns that
    class of mistake into a test failure rather than a surprise in someone's
    home directory.
    """
    from blue_data_user_cli.profile import cli_spec

    # Clear every configurable parameter first, so a developer's own exported
    # OPENAI_API_KEY (or any other) cannot change what these tests observe.
    for param in cli_spec():
        monkeypatch.delenv(param.name, raising=False)
    monkeypatch.delenv("BLUE_DATA_PROFILE", raising=False)

    for var in _HOME_ENV_VARS:
        monkeypatch.setenv(var, str(data_dir))

    yield

    real_home = Path.home() / ".blue-userdb"
    if real_home.exists():
        touched = [
            f.name for f in real_home.iterdir()
            if f.stat().st_mtime >= _SESSION_START
        ]
        assert not touched, (
            f"CLI tests wrote into the real {real_home}: {touched}. "
            f"Something resolved a path outside tmp_path — check that every "
            f"home/data environment variable is listed in _HOME_ENV_VARS."
        )


@pytest.fixture
def runner(isolated_home) -> CliRunner:
    return IsolatedRunner()
