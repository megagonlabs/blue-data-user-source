from __future__ import annotations

from pathlib import Path
from typing import Any

from blue_data_user_source import FileUserSource
from blue_data_user_source.data.manager import CLS_JSON_FILE
from blue_data_user_source.interaction.pending import pending_interactions  # noqa: F401 (re-exported)

_CLS_KB_FILE = "blue_data_kb_source.file_kb_source.FileKBSource"


def _default_user_props(name: str, data_dir: Path) -> dict[str, Any]:
    base = data_dir / "sources" / name
    return {
        "registry": {
            "_class": CLS_JSON_FILE,
            "connection": {"protocol": "json/file", "path": str(data_dir / "registries" / f"{name}.json")},
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


def create_source(data_dir: Path, schema_path: str = "") -> FileUserSource:
    props: dict[str, Any] = {"connection": {"path": str(data_dir / "registry.json")}}
    if schema_path:
        props["schema"] = schema_path
    return FileUserSource("user_source", props)
