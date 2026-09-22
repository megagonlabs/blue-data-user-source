"""Configuration comes from the environment, and only from the environment.

The API server shares parameter *names* with the `blue-userdb` CLI but none of its
machinery: it must not read `~/.blue-userdb/.profiles` or the selected profile, so a
developer's CLI profile cannot silently reconfigure a running server.
"""
from __future__ import annotations

import ast
from pathlib import Path

from blue_data_user_api.config import Settings
from blue_data_user_api.source import create_source

_SCHEMA_SETTINGS = {
    "BLUE_DATA_USER_SOURCE_SCHEMA_PATH": "schema_path",
    "BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH": "metadata_schema_path",
    "BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH": "contact_schema_path",
}


def test_schema_paths_come_from_the_environment(monkeypatch):
    """Same variable names the CLI uses, read straight from the environment."""
    for var in _SCHEMA_SETTINGS:
        monkeypatch.setenv(var, f"/schemas/{var}.json")
    settings = Settings(_env_file=None)
    for var, field in _SCHEMA_SETTINGS.items():
        assert getattr(settings, field) == f"/schemas/{var}.json"


def test_schema_paths_default_to_empty(monkeypatch):
    for var in _SCHEMA_SETTINGS:
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)
    for field in _SCHEMA_SETTINGS.values():
        assert getattr(settings, field) == ""


def test_create_source_passes_the_configured_paths(tmp_path):
    source = create_source(
        tmp_path,
        schema_path="/schemas/schema.json",
        metadata_schema_path="/schemas/metadata.json",
        contact_schema_path="/schemas/contacts.json",
    )
    assert source.properties["schema"] == "/schemas/schema.json"
    assert source.properties["metadata_schema"] == "/schemas/metadata.json"
    assert source.properties["contact_schema"] == "/schemas/contacts.json"


def test_unset_paths_are_left_to_the_library_defaults(tmp_path):
    source = create_source(tmp_path)
    for prop in ("schema", "metadata_schema", "contact_schema"):
        assert prop not in source.properties


def test_a_cli_profile_does_not_configure_the_server(tmp_path, monkeypatch):
    """A `.profiles` file on disk is inert here — only the environment counts."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".profiles").write_text(
        "[default]\n"
        "BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH = /from/the/profile.json\n"
    )
    (home / ".selected.profile").write_text("default")
    monkeypatch.setenv("BLUE_DATA_USER_SOURCE_HOME", str(home))
    monkeypatch.delenv("BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH", raising=False)

    assert Settings(_env_file=None).metadata_schema_path == ""


def test_the_server_does_not_import_the_cli():
    """The package depends only on blue-data-user-source, like the MCP server."""
    import blue_data_user_api

    source = Path(blue_data_user_api.__file__).parent
    imported: set[str] = set()
    for path in source.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    assert not [m for m in imported if m.startswith("blue_data_user_cli")]
