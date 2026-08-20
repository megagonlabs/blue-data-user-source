"""UserSource singleton factory — reads all config from environment variables.

The server owns a single FileUserSource instance for the process lifetime,
configured entirely by UDB_* env vars. `user` is passed as an argument on
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
from blue_data_user_source.data.manager import CLS_JSON_FILE

_CLS_KB_FILE = "blue_data_kb_source.file_kb_source.FileKBSource"

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


def default_user_props(name: str) -> dict[str, Any]:
    """Derive all four sub-source configs from get_data_dir() for a given user name."""
    d = get_data_dir()
    base = d / "sources" / name
    return {
        "registry": {
            "_class": CLS_JSON_FILE,
            "connection": {"protocol": "json/file", "path": str(d / "registries" / f"{name}.json")},
        },
        "kb_source": {
            "_class": _CLS_KB_FILE,
            "connection": {"protocol": "kb/file", "directory": str(base)},
        },
        "metadata_source": {
            "_class": CLS_JSON_FILE,
            "connection": {"protocol": "json/file", "path": str(base / "metadata.json")},
        },
        "contact_source": {
            "_class": CLS_JSON_FILE,
            "connection": {"protocol": "json/file", "path": str(base / "contacts.json")},
        },
    }


def _build_source() -> tuple[FileUserSource, Path]:
    d = Path(os.environ.get("UDB_DATA_DIR", "~/.udb")).expanduser().resolve()
    d.mkdir(parents=True, exist_ok=True)
    props: dict[str, Any] = {"connection": {"path": str(d / "registry.json")}}
    schema = os.environ.get("UDB_SCHEMA_PATH", "")
    if schema:
        props["schema"] = schema
    return FileUserSource("user_source", props), d
