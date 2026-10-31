"""A UserSource asks at this process's console only when its owner says so (#186, #191).

A registry host rebuilds a source from blue-data's record of it. Defaulting to
True wrote the clarification prompt into an MCP stdio server's JSON-RPC stream
(#186); defaulting to "stdin and stdout are terminals" (#189) still put a
blue-data-api started at a terminal on a ``> `` prompt, its REST request never
returning; and a source registered with ``console=True`` had it stored in the
record, so every host rebuilt it with the console. ``console`` now defaults to
False and is held apart from ``properties``, so no record carries it.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from blue_data.registry.data_registry import DataRegistry
from blue_data.source.json.file_json_source import FileJSONSource

from blue_data_user_source import FileUserSource


class _Stream(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """stdin and stdout are terminals, as for a server started in the foreground."""
    monkeypatch.setattr(sys, "stdin", _Stream(True))
    monkeypatch.setattr(sys, "stdout", _Stream(True))


def _registry(tmp_path: Path) -> DataRegistry:
    store = FileJSONSource(properties={"connection": {"path": str(tmp_path / "store.json")}})
    return DataRegistry(store=store)


def _source(tmp_path: Path, **props) -> FileUserSource:
    return FileUserSource("users", {"connection": {"path": str(tmp_path / "users.json")}, **props})


def _rebuilt(tmp_path: Path, **props) -> FileUserSource:
    """The source as a registry host gets it: registered, then rebuilt from its record."""
    _registry(tmp_path).register_source(_source(tmp_path, **props))
    source = _registry(tmp_path).connect_source("users")
    assert isinstance(source, FileUserSource)
    return source


def test_a_source_nobody_configured_has_no_console_even_at_a_terminal(tmp_path, terminal) -> None:
    assert _source(tmp_path).console is False


def test_a_rebuilt_source_has_no_console_even_at_a_terminal(tmp_path, terminal) -> None:
    """(a): blue-data-api in the foreground of a terminal."""
    assert _rebuilt(tmp_path).console is False


def test_console_true_is_not_stored_in_the_registry_record(tmp_path) -> None:
    """(b): registered with console=True, e.g. from an interactive script."""
    source = _source(tmp_path, console=True)
    assert source.console is True
    assert "console" not in source.properties
    _registry(tmp_path).register_source(source)
    [record] = [r for r in _registry(tmp_path).get_sources() if r.get("name") == "users"]
    assert "console" not in record.get("properties", {})
    assert _rebuilt(tmp_path, console=True).console is False


def test_a_record_stored_with_console_before_the_fix_is_rebuilt_without(tmp_path) -> None:
    registry = _registry(tmp_path)
    source = _source(tmp_path)
    registry.register_source(source)
    registry.set_source_property("users", "console", True)  # as blue-data stored it before #191
    assert _registry(tmp_path).connect_source("users").console is False


@pytest.mark.parametrize("console", [True, False])
def test_an_explicit_console_prop_is_kept(tmp_path, console: bool) -> None:
    assert _source(tmp_path, console=console).console is console


def test_the_callers_properties_are_not_changed(tmp_path) -> None:
    props = {"connection": {"path": str(tmp_path / "users.json")}, "console": True}
    FileUserSource("users", props)
    assert props["console"] is True
