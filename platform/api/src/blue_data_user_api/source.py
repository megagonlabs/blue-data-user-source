from __future__ import annotations

from pathlib import Path
from typing import Any

from blue_data_user_source import FileUserSource
from blue_data_user_source.interaction.pending import pending_interactions  # noqa: F401 (re-exported)


def create_source(
    data_dir: Path,
    schema_path: str = "",
    metadata_schema_path: str = "",
    contact_schema_path: str = "",
) -> FileUserSource:
    # The server's stdin/stdout are not the user's, so it must never ask the user on them.
    props: dict[str, Any] = {"connection": {"path": str(data_dir / "registry.json")}, "console": False}
    for prop, value in (
        ("schema", schema_path),
        ("metadata_schema", metadata_schema_path),
        ("contact_schema", contact_schema_path),
    ):
        if value:
            props[prop] = value
    return FileUserSource("user_source", props)
