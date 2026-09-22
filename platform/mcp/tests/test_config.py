"""Configuration comes from the environment, and only from the environment.

The MCP server shares parameter *names* with the `blue-userdb` CLI but none of its
machinery: it must not read `~/.blue-userdb/.profiles` or the selected profile, so a
developer's CLI profile cannot silently reconfigure a running server.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import blue_data_user_mcp.config as config_module

_SCHEMA_VARS = {
    "BLUE_DATA_USER_SOURCE_SCHEMA_PATH": "schema",
    "BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH": "metadata_schema",
    "BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH": "contact_schema",
}


def _props(tmp_path: Path, monkeypatch) -> dict:
    """The properties `_build_source` hands to FileUserSource, without the I/O."""
    monkeypatch.setenv("BLUE_DATA_USER_SOURCE_DATA_DIR", str(tmp_path))
    with patch.object(config_module, "FileUserSource") as source_cls:
        config_module._build_source()
    return source_cls.call_args.args[1]


def test_schema_paths_come_from_the_environment(tmp_path, monkeypatch):
    for var in _SCHEMA_VARS:
        monkeypatch.setenv(var, f"/schemas/{var}.json")
    props = _props(tmp_path, monkeypatch)
    for var, prop in _SCHEMA_VARS.items():
        assert props[prop] == f"/schemas/{var}.json"


def test_unset_schema_paths_are_left_to_the_library_defaults(tmp_path, monkeypatch):
    for var in _SCHEMA_VARS:
        monkeypatch.delenv(var, raising=False)
    props = _props(tmp_path, monkeypatch)
    for prop in _SCHEMA_VARS.values():
        assert prop not in props


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

    props = _props(tmp_path, monkeypatch)
    assert "metadata_schema" not in props


def test_the_server_does_not_import_the_cli():
    """The package depends only on blue-data-user-source; see config.py's docstring.

    Checked on the import statements rather than the file text, since the
    docstring naming the CLI is exactly the point.
    """
    import ast

    source = Path(config_module.__file__).parent
    imported: set[str] = set()
    for path in source.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    assert not [m for m in imported if m.startswith("blue_data_user_cli")]
