"""A UserSource nobody configured stays off a console it does not have (#186).

``console`` is not stored in blue-data's registry, so a source the registry
rebuilds takes the default. Hosted by a server whose stdin/stdout are pipes
(``blue-data-registry-mcp`` over stdio) a default of True wrote the clarification
prompt into the JSON-RPC stream. The default is now whether stdin and stdout are
both terminals.
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


def _streams(monkeypatch: pytest.MonkeyPatch, stdin_tty: bool, stdout_tty: bool) -> None:
    monkeypatch.setattr(sys, "stdin", _Stream(stdin_tty))
    monkeypatch.setattr(sys, "stdout", _Stream(stdout_tty))


def _rebuilt(tmp_path: Path) -> FileUserSource:
    """The source as a registry host gets it: registered, then rebuilt from its record."""
    store = tmp_path / "store.json"
    def registry() -> DataRegistry:
        return DataRegistry(store=FileJSONSource(properties={"connection": {"path": str(store)}}))

    path = str(tmp_path / "users" / "registry.json")
    registry().register_source(FileUserSource("users", {"connection": {"path": path}}))
    return registry().connect_source("users")


def test_rebuilt_source_under_pipes_has_no_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _streams(monkeypatch, stdin_tty=False, stdout_tty=False)
    source = _rebuilt(tmp_path)
    assert isinstance(source, FileUserSource)
    assert source.console is False


def test_rebuilt_source_at_a_terminal_has_the_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _streams(monkeypatch, stdin_tty=True, stdout_tty=True)
    assert _rebuilt(tmp_path).console is True


@pytest.mark.parametrize(("stdin_tty", "stdout_tty"), [(True, False), (False, True)])
def test_one_stream_redirected_is_no_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdin_tty: bool, stdout_tty: bool
) -> None:
    _streams(monkeypatch, stdin_tty, stdout_tty)
    source = FileUserSource("u", {"connection": {"path": str(tmp_path / "registry.json")}})
    assert source.console is False


def test_closed_stdin_is_no_console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr(sys, "stdout", _Stream(True))
    source = FileUserSource("u", {"connection": {"path": str(tmp_path / "registry.json")}})
    assert source.console is False


@pytest.mark.parametrize("console", [True, False])
def test_an_explicit_console_prop_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, console: bool
) -> None:
    _streams(monkeypatch, stdin_tty=not console, stdout_tty=not console)
    path = str(tmp_path / "registry.json")
    source = FileUserSource("u", {"connection": {"path": path}, "console": console})
    assert source.console is console
