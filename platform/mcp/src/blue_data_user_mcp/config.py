"""UserSource singleton factory — reads all config from environment variables.

The server owns a single FileUserSource instance for the process lifetime,
configured entirely by BLUE_DATA_USER_SOURCE_* env vars. `user` is passed as an argument on
every tool call — UserSource already supports multiple users (databases) on
one registry.

Deliberately does not import anything from blue_data_user_cli: this package
depends only on blue-data-user-source, so it can be built, versioned, and
deployed independently.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from blue_data_user_source import FileUserSource


_source: Optional[FileUserSource] = None
_data_dir: Optional[Path] = None


def get_source() -> FileUserSource:
    global _source, _data_dir
    if _source is None:
        _source, _data_dir = _build_source()
    return _source


def get_data_dir() -> Path:
    get_source()
    assert _data_dir is not None
    return _data_dir


def reset_source() -> None:
    """Replace the singleton with a fresh instance — for tests."""
    global _source, _data_dir
    _source = None
    _data_dir = None


def _build_source() -> tuple[FileUserSource, Path]:
    d = Path(os.environ.get("BLUE_DATA_USER_SOURCE_DATA_DIR", "~/.blue-userdb")).expanduser().resolve()
    d.mkdir(parents=True, exist_ok=True)
    # A server's stdin/stdout are not the user's (for the stdio transport, stdout
    # is the protocol stream), so it must never ask the user on them.
    props: dict[str, Any] = {"connection": {"path": str(d / "registry.json")}, "console": False}
    for prop, var in (
        ("schema", "BLUE_DATA_USER_SOURCE_SCHEMA_PATH"),
        ("metadata_schema", "BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH"),
        ("contact_schema", "BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH"),
    ):
        value = os.environ.get(var, "")
        if value:
            props[prop] = value
    return FileUserSource("user_source", props), d
