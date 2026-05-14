import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from blue_data_user_cli.commands import cli
from blue_data_user_source.types import QueryError, QueryResult


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def txt_file(tmp_path: Path) -> Path:
    f = tmp_path / "resume.txt"
    f.write_text("Python\nSQL\n")
    return f


def _mock_source(results: list[QueryResult] | None = None) -> Any:
    instance = AsyncMock()
    instance.execute_query = AsyncMock(return_value=results or [])
    instance.import_source = AsyncMock(return_value=None)
    instance.create_database = AsyncMock(return_value=None)
    return instance


# ── query command ─────────────────────────────────────────────────────────────

def test_query_table_output_contains_result_query(runner: CliRunner) -> None:
    mock = _mock_source([QueryResult(query="What skills?", results=["Python"])])
    with patch("blue_data_user_cli.commands._make_source", return_value=mock):
        result = runner.invoke(cli, ["--user", "db", "query", "skills?"])
    assert result.exit_code == 0
    assert "What skills?" in result.output


def test_query_json_format_outputs_valid_json(runner: CliRunner) -> None:
    mock = _mock_source([QueryResult(query="q", results=["x"])])
    with patch("blue_data_user_cli.commands._make_source", return_value=mock):
        result = runner.invoke(cli, ["--user", "db", "query", "q", "--format", "json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["query"] == "q"
    assert parsed[0]["results"] == ["x"]


def test_query_passes_session_to_execute_query(runner: CliRunner) -> None:
    mock = _mock_source([])
    with patch("blue_data_user_cli.commands._make_source", return_value=mock):
        runner.invoke(cli, ["--user", "db", "query", "q", "--session", "sess-1"])
    mock.execute_query.assert_awaited_once_with(
        "q", optional_properties={"session": "sess-1"}
    )


def test_query_no_session_passes_none_props(runner: CliRunner) -> None:
    mock = _mock_source([])
    with patch("blue_data_user_cli.commands._make_source", return_value=mock):
        runner.invoke(cli, ["--user", "db", "query", "q"])
    mock.execute_query.assert_awaited_once_with("q", optional_properties=None)


def test_query_error_exits_with_code_1(runner: CliRunner) -> None:
    mock = _mock_source()
    mock.execute_query = AsyncMock(side_effect=QueryError("no db"))
    with patch("blue_data_user_cli.commands._make_source", return_value=mock):
        result = runner.invoke(cli, ["query", "q"])
    assert result.exit_code == 1


# ── import command ────────────────────────────────────────────────────────────

def test_import_type1_prints_registered(runner: CliRunner, txt_file: Path) -> None:
    mock = _mock_source()
    with patch("blue_data_user_cli.commands._make_source", return_value=mock):
        result = runner.invoke(cli, ["--user", "db", "import", str(txt_file)])
    assert result.exit_code == 0
    assert "Registered" in result.output
    mock.import_source.assert_awaited_once()


def test_import_type2_prints_imported_with_query_count(
    runner: CliRunner, txt_file: Path
) -> None:
    mock = _mock_source()
    with patch("blue_data_user_cli.commands._make_source", return_value=mock):
        result = runner.invoke(
            cli,
            [
                "--user", "db",
                "import", str(txt_file),
                "--query", "What skills?",
                "--query", "Remote?",
            ],
        )
    assert result.exit_code == 0
    assert "2" in result.output and "queries" in result.output


def test_import_type2_passes_queries_to_import_source(
    runner: CliRunner, txt_file: Path
) -> None:
    mock = _mock_source()
    with patch("blue_data_user_cli.commands._make_source", return_value=mock):
        runner.invoke(
            cli,
            ["--user", "db", "import", str(txt_file), "--query", "Skills?"],
        )
    _call = mock.import_source.await_args
    assert _call is not None
    props = _call.kwargs.get("optional_properties") or _call.args[1]
    assert "Skills?" in props["queries"]


def test_import_missing_file_exits_with_code_2(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--user", "db", "import", "/no/such/file.txt"])
    assert result.exit_code == 2


# ── user create command ───────────────────────────────────────────────────────

def test_user_create_prints_created(runner: CliRunner) -> None:
    mock = _mock_source()
    with patch("blue_data_user_cli.commands._make_source", return_value=mock):
        result = runner.invoke(cli, ["user", "create", "my-db"])
    assert result.exit_code == 0
    assert "my-db" in result.output


def test_user_create_calls_create_database(runner: CliRunner) -> None:
    mock = _mock_source()
    with patch("blue_data_user_cli.commands._make_source", return_value=mock):
        runner.invoke(cli, ["user", "create", "my-db"])
    mock.create_database.assert_awaited_once_with("my-db")


def test_user_create_error_exits_with_code_1(runner: CliRunner) -> None:
    mock = _mock_source()
    mock.create_database = AsyncMock(side_effect=QueryError("fail"))
    with patch("blue_data_user_cli.commands._make_source", return_value=mock):
        result = runner.invoke(cli, ["user", "create", "x"])
    assert result.exit_code == 1


# ── _make_source / global --user and --data-dir flags ────────────────────────

def test_user_flag_is_passed_to_source_factory(runner: CliRunner, tmp_path: Path) -> None:
    mock = _mock_source([])
    with patch("blue_data_user_cli.commands._make_source", return_value=mock) as factory:
        runner.invoke(cli, ["--user", "target-db", "--data-dir", str(tmp_path), "query", "q"])
    factory.assert_called_once_with("target-db", tmp_path)


def test_no_user_flag_passes_none_to_factory(runner: CliRunner, tmp_path: Path) -> None:
    mock = _mock_source([])
    with patch("blue_data_user_cli.commands._make_source", return_value=mock) as factory:
        runner.invoke(cli, ["--data-dir", str(tmp_path), "query", "q"])
    factory.assert_called_once_with(None, tmp_path)
