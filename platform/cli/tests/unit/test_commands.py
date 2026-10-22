"""Tests for the `blue-userdb` CLI.

Every test patches ``blue_data_user_cli.commands._make_source`` with a mock
UserSource so no real registry/KB/LLM calls happen, and always passes an
isolated ``--data-dir`` (a pytest tmp_path) since ``_get_db``/selection files
touch the real filesystem regardless of the source mock.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from blue_data_user_source.types import QueryError
from click.testing import CliRunner

from blue_data_user_cli.commands import cli


def _invoke(runner: CliRunner, data_dir: Path, args: list[str], database: str | None = None):
    base = ["--data-dir", str(data_dir)]
    if database:
        base += ["--database", database]
    return runner.invoke(cli, base + args)


def _select_database(data_dir: Path, name: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / ".selected.database").write_text(name)


def _kb_source(**async_methods: Any) -> MagicMock:
    """MagicMock KB source with the given methods configured as AsyncMock(return_value=...)."""
    kb = MagicMock()
    for name, value in async_methods.items():
        setattr(kb, name, AsyncMock(return_value=value))
    return kb


def _manager_with_kb(kb: MagicMock) -> MagicMock:
    manager = MagicMock()
    manager._ensure_kb_source.return_value = kb
    return manager


def _source_with_manager(manager: MagicMock) -> MagicMock:
    source = MagicMock()
    source._get_manager.return_value = manager
    return source


def _patched(mock: Any):
    return patch("blue_data_user_cli.commands._make_source", return_value=mock)


# ── global: database resolution ───────────────────────────────────────────────

def test_no_database_selected_exits_with_code_1(runner: CliRunner, data_dir: Path) -> None:
    mock = MagicMock()
    with _patched(mock):
        result = _invoke(runner, data_dir, ["metadata", "list"])
    assert result.exit_code == 1
    assert "No database selected" in result.output


def test_database_flag_overrides_selection_file(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "ignored-selected-db")
    mock = MagicMock()
    mock.list_metadata.return_value = {}
    with _patched(mock):
        result = _invoke(runner, data_dir, ["metadata", "list"], database="from-flag")
    assert result.exit_code == 0
    mock.list_metadata.assert_called_once_with("from-flag")


# ── database group ────────────────────────────────────────────────────────────

def test_database_list_shows_registered_names(runner: CliRunner, data_dir: Path) -> None:
    mock = MagicMock()
    mock.list_users.return_value = ["alice", "bob"]
    mock.get_user.return_value = {"registry": {"connection": {"protocol": "json/memory"}}}
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "list"])
    assert result.exit_code == 0
    assert "alice" in result.output
    assert "bob" in result.output


def test_database_list_empty_produces_placeholder(runner: CliRunner, data_dir: Path) -> None:
    mock = MagicMock()
    mock.list_users.return_value = []
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "list"])
    assert result.exit_code == 0
    assert "no databases" in result.output


@patch("blue_data_user_cli.commands._interactive", return_value=True)
def test_database_create_onboards_by_default(_interactive, runner: CliRunner, data_dir: Path) -> None:
    mock = MagicMock()
    mock.list_users.return_value = []
    mock.create_user = AsyncMock(return_value=None)
    mock.onboard_user = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "create", "alice"])
    assert result.exit_code == 0
    assert "alice" in result.output
    assert mock.create_user.await_args.kwargs["onboard"] is False  # onboarded as its own step
    mock.onboard_user.assert_awaited_once_with("alice", include_metadata=True)


@patch("blue_data_user_cli.commands._interactive", return_value=True)
def test_database_create_keeps_the_database_when_onboarding_fails(_interactive, 
    runner: CliRunner, data_dir: Path
) -> None:
    """An unreachable LLM fails onboarding, not the creation that already happened (#117)."""
    from blue_data_user_source import LLMError

    mock = MagicMock()
    mock.list_users.return_value = []
    mock.create_user = AsyncMock(return_value=None)
    mock.onboard_user = AsyncMock(return_value=None)
    mock.onboard_user = AsyncMock(side_effect=LLMError("LLM call to 'gpt-4o' failed: down"))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "create", "alice"])
    assert result.exit_code == 0, result.output
    assert "Created database: alice (selected)" in result.output
    assert "onboarding did not run" in result.output and "database onboard" in result.output
    assert (data_dir / ".selected.database").read_text() == "alice"


def test_database_create_no_onboard_flag_disables_onboarding(
    runner: CliRunner, data_dir: Path
) -> None:
    mock = MagicMock()
    mock.list_users.return_value = []
    mock.create_user = AsyncMock(return_value=None)
    mock.onboard_user = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "create", "alice", "--no-onboard"])
    assert result.exit_code == 0
    assert mock.create_user.await_args.kwargs["onboard"] is False
    mock.onboard_user.assert_not_called()


@patch("blue_data_user_cli.commands._interactive", return_value=True)
def test_database_create_no_metadata_onboard_flag(_interactive, 
    runner: CliRunner, data_dir: Path
) -> None:
    mock = MagicMock()
    mock.list_users.return_value = []
    mock.create_user = AsyncMock(return_value=None)
    mock.onboard_user = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "create", "alice", "--no-metadata-onboard"])
    assert result.exit_code == 0
    mock.onboard_user.assert_awaited_once_with("alice", include_metadata=False)


def test_database_create_already_exists_exits_with_code_1(
    runner: CliRunner, data_dir: Path
) -> None:
    mock = MagicMock()
    mock.list_users.return_value = ["alice"]
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "create", "alice"])
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_database_create_neo4j_without_password_exits_with_code_1(
    runner: CliRunner, data_dir: Path
) -> None:
    mock = MagicMock()
    mock.list_users.return_value = []
    with _patched(mock):
        result = _invoke(
            runner, data_dir, ["database", "create", "alice", "--kb-backend", "neo4j"]
        )
    assert result.exit_code == 1
    assert "BLUE_DATA_USER_SOURCE_NEO4J_PASSWORD" in result.output  # points at the profile, not a CLI argument


def test_database_create_error_exits_with_code_1(runner: CliRunner, data_dir: Path) -> None:
    mock = MagicMock()
    mock.list_users.return_value = []
    mock.create_user = AsyncMock(side_effect=QueryError("boom"))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "create", "alice"])
    assert result.exit_code == 1


# ── database create: KB search index config ────────────────────────────────────

def test_database_create_defaults_kb_search_mode_to_bm25(runner: CliRunner, data_dir: Path) -> None:
    """Without --kb-search-mode, new users get a working schema/data search index
    (bm25) rather than falling back to the much weaker exact-substring lookup."""
    mock = MagicMock()
    mock.list_users.return_value = []
    mock.create_user = AsyncMock(return_value=None)
    mock.onboard_user = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "create", "alice"])
    assert result.exit_code == 0
    kb_props = mock.create_user.await_args.args[2]
    assert kb_props["search"]["mode"] == "bm25"
    assert "bm25_index_dir" in kb_props["search"]


def test_database_create_kb_search_mode_none_omits_search_key(
    runner: CliRunner, data_dir: Path
) -> None:
    mock = MagicMock()
    mock.list_users.return_value = []
    mock.create_user = AsyncMock(return_value=None)
    mock.onboard_user = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(
            runner, data_dir, ["database", "create", "alice", "--kb-search-mode", "none"]
        )
    assert result.exit_code == 0
    kb_props = mock.create_user.await_args.args[2]
    assert "search" not in kb_props


def test_database_create_kb_search_bm25_omits_index_dir_for_memory_backend(
    runner: CliRunner, data_dir: Path
) -> None:
    """The memory KB backend has no persistent directory of its own, so the BM25
    corpus (also ephemeral) doesn't get one either."""
    mock = MagicMock()
    mock.list_users.return_value = []
    mock.create_user = AsyncMock(return_value=None)
    mock.onboard_user = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(
            runner, data_dir, ["database", "create", "alice", "--kb-backend", "memory"]
        )
    assert result.exit_code == 0
    kb_props = mock.create_user.await_args.args[2]
    assert kb_props["search"] == {"mode": "bm25"}


def test_database_create_kb_search_mode_semantic_builds_vector_and_embedding_config(
    runner: CliRunner, data_dir: Path
) -> None:
    mock = MagicMock()
    mock.list_users.return_value = []
    mock.create_user = AsyncMock(return_value=None)
    mock.onboard_user = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(
            runner, data_dir,
            [
                "database", "create", "alice",
                "--kb-search-mode", "semantic",
                "--kb-vector-backend", "memory",
                "--kb-embedding-model", "text-embedding-3-large",
            ],
        )
    assert result.exit_code == 0
    search = mock.create_user.await_args.args[2]["search"]
    assert search["mode"] == "semantic"
    assert search["vector"]["connection"] == {"protocol": "vector/memory"}
    assert search["embedding"] == {"provider": "openai", "model": "text-embedding-3-large"}


def test_database_onboard_calls_onboard_user(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.onboard_user = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "onboard"])
    assert result.exit_code == 0
    assert "alice" in result.output
    mock.onboard_user.assert_awaited_once_with("alice", include_metadata=True)


def test_database_onboard_no_metadata_onboard_flag(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.onboard_user = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "onboard", "--no-metadata-onboard"])
    assert result.exit_code == 0
    mock.onboard_user.assert_awaited_once_with("alice", include_metadata=False)


def test_database_onboard_error_exits_with_code_1(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.onboard_user = AsyncMock(side_effect=QueryError("no contact method"))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "onboard"])
    assert result.exit_code == 1


def test_database_delete_removes_and_prints(runner: CliRunner, data_dir: Path) -> None:
    mock = MagicMock()
    mock.delete_user = AsyncMock(return_value=[])  # the paths it refused to delete (#156)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "delete", "alice", "--yes"])
    assert result.exit_code == 0
    assert "Deleted" in result.output
    mock.delete_user.assert_awaited_once_with("alice")


def test_database_delete_error_exits_with_code_1(runner: CliRunner, data_dir: Path) -> None:
    mock = MagicMock()
    mock.delete_user = AsyncMock(side_effect=QueryError("not found"))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "delete", "alice", "--yes"])
    assert result.exit_code == 1


def test_database_select_writes_selection(runner: CliRunner, data_dir: Path) -> None:
    mock = MagicMock()
    mock.list_users.return_value = ["alice"]
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "select", "alice"])
    assert result.exit_code == 0
    assert (data_dir / ".selected.database").read_text() == "alice"


def test_database_select_unknown_name_exits_with_code_1(
    runner: CliRunner, data_dir: Path
) -> None:
    mock = MagicMock()
    mock.list_users.return_value = []
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "select", "ghost"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_database_search_filters_by_keyword(runner: CliRunner, data_dir: Path) -> None:
    mock = MagicMock()
    mock.list_users.return_value = ["alice", "bob", "alicia"]
    mock.get_user.return_value = {"registry": {"connection": {"protocol": "json/memory"}}}
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "search", "ali"])
    assert result.exit_code == 0
    assert "alice" in result.output
    assert "alicia" in result.output
    assert "bob" not in result.output


def test_database_search_table_format_renders_a_table(
    runner: CliRunner, data_dir: Path
) -> None:
    """`--format table` printed bare names before; it now renders the same
    columns `database list` does."""
    mock = MagicMock()
    mock.list_users.return_value = ["alice"]
    mock.get_user.return_value = {"registry": {"connection": {"protocol": "json/file"}}}
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "search", "ali", "--format", "table"])
    assert result.exit_code == 0
    assert "Name" in result.output and "Registry" in result.output
    assert "json/file" in result.output
    assert "┃" in result.output or "|" in result.output


def test_database_delete_warns_about_paths_it_kept(runner: CliRunner, data_dir: Path) -> None:
    """A recorded path outside the data directory is not deleted, and the CLI says so (#156)."""
    mock = MagicMock()
    mock.delete_user = AsyncMock(return_value=["/elsewhere/metadata.json"])
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "delete", "alice", "--yes"])
    assert result.exit_code == 0, result.output
    assert "not deleted, outside the data directory: /elsewhere/metadata.json" in result.output


def test_database_reset_confirmed_calls_reset_user(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.reset_user = AsyncMock(return_value=[])
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "reset", "--yes"])
    assert result.exit_code == 0
    mock.reset_user.assert_awaited_once_with("alice")


def test_database_config_show_displays_properties(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.get_user.return_value = {"registry": {"connection": {"protocol": "json/file"}}}
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "config", "show"])
    assert result.exit_code == 0
    assert "json/file" in result.output


# ── session group ──────────────────────────────────────────────────────────────

def test_session_start_creates_and_selects_session(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.create_session = AsyncMock(return_value="sess-1")
    with _patched(mock):
        result = _invoke(runner, data_dir, ["session", "start"])
    assert result.exit_code == 0
    assert "sess-1" in result.output
    assert (data_dir / ".selected.session").read_text() == "sess-1"


def test_session_select_unknown_id_exits_with_code_1(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.get_session = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["session", "select", "sess-x"])
    assert result.exit_code == 1


def test_session_end_clears_matching_selection(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    (data_dir / ".selected.session").write_text("sess-1")
    mock = MagicMock()
    mock.end_session = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["session", "end", "sess-1"])
    assert result.exit_code == 0
    assert not (data_dir / ".selected.session").exists()


def test_session_list_shows_sessions(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_sessions = AsyncMock(return_value={
        "sess-1": {"status": "active", "queries": {}, "created_at": None},
    })
    with _patched(mock):
        result = _invoke(runner, data_dir, ["session", "list"])
    assert result.exit_code == 0
    assert "sess-1" in result.output


def test_session_show_renders_tables(runner: CliRunner, data_dir: Path) -> None:
    """`--format table` printed prose lines before; the session, its queries and
    its interactions each get a real table now."""
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.get_session = AsyncMock(return_value={
        "status": "open",
        "created_at": "2026-09-16T10:00:00+00:00",
        "queries": {
            "q1": {
                "query": "What are alice's skills?",
                "interactions": {
                    "i1": {
                        "status": "answered",
                        "contact": {"protocol": "email"},
                        "question": "Which role?",
                        "response": "Backend.",
                    },
                },
            },
        },
    })
    with _patched(mock):
        result = _invoke(runner, data_dir, ["session", "show", "sess-1"])
    assert result.exit_code == 0, result.output
    # session detail table
    assert "Field" in result.output and "Status" in result.output
    # per-level tables
    assert "Queries" in result.output and "Interactions" in result.output
    assert "Which role?" in result.output and "Backend." in result.output
    assert "email" in result.output


def test_session_show_without_interactions_omits_that_table(
    runner: CliRunner, data_dir: Path
) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.get_session = AsyncMock(return_value={
        "status": "open",
        "created_at": "2026-09-16T10:00:00+00:00",
        "queries": {"q1": {"query": "skills?", "interactions": {}}},
    })
    with _patched(mock):
        result = _invoke(runner, data_dir, ["session", "show", "sess-1"])
    assert result.exit_code == 0, result.output
    assert "Which role?" not in result.output
    assert "skills?" in result.output


def test_session_show_not_found_exits_with_code_1(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.get_session = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["session", "show", "sess-x"])
    assert result.exit_code == 1


# ── data group ─────────────────────────────────────────────────────────────────

def test_data_query_table_output_contains_result(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.async_execute_query = AsyncMock(return_value=([{"skill": "Python"}], "sess-1"))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "query", "skills?"])
    assert result.exit_code == 0
    assert "Python" in result.output


def test_data_query_json_format_outputs_valid_json(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.async_execute_query = AsyncMock(return_value=([{"skill": "Python"}], "sess-1"))
    with _patched(mock):
        result = _invoke(
            runner, data_dir, ["data", "query", "skills?", "--format", "json"]
        )
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed == [{"skill": "Python"}]


def test_data_query_nl_format_echoes_answer(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.async_execute_query = AsyncMock(return_value=("Alice knows Python.", "sess-1"))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "query", "skills?", "--format", "nl"])
    assert result.exit_code == 0
    assert "Alice knows Python." in result.output


def test_data_query_selects_new_session_when_none_given(
    runner: CliRunner, data_dir: Path
) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.async_execute_query = AsyncMock(return_value=([], "sess-new"))
    with _patched(mock):
        _invoke(runner, data_dir, ["data", "query", "q"])
    assert (data_dir / ".selected.session").read_text() == "sess-new"


def test_root_session_option_is_forwarded(runner: CliRunner, data_dir: Path) -> None:
    """`--session` is a root option like `--database`, not just a `data query` one."""
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.async_execute_query = AsyncMock(return_value=([], "sess-1"))
    with _patched(mock):
        result = runner.invoke(
            cli, ["--data-dir", str(data_dir), "--session", "sess-root", "data", "query", "q"]
        )
    assert result.exit_code == 0, result.output
    assert mock.async_execute_query.call_args.kwargs["optional_properties"]["session"] == "sess-root"


def test_session_env_var_is_forwarded(runner: CliRunner, data_dir: Path, monkeypatch) -> None:
    """BLUE_DATA_USER_SOURCE_SESSION used to be read inline in _get_session; it is
    now a declared parameter resolved like every other one."""
    _select_database(data_dir, "alice")
    monkeypatch.setenv("BLUE_DATA_USER_SOURCE_SESSION", "sess-env")
    mock = MagicMock()
    mock.async_execute_query = AsyncMock(return_value=([], "sess-1"))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "query", "q"])
    assert result.exit_code == 0, result.output
    assert mock.async_execute_query.call_args.kwargs["optional_properties"]["session"] == "sess-env"


def test_command_session_option_outranks_the_root_one(
    runner: CliRunner, data_dir: Path
) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.async_execute_query = AsyncMock(return_value=([], "sess-1"))
    with _patched(mock):
        result = runner.invoke(cli, [
            "--data-dir", str(data_dir), "--session", "sess-root",
            "data", "query", "q", "--session", "sess-cmd",
        ])
    assert result.exit_code == 0, result.output
    assert mock.async_execute_query.call_args.kwargs["optional_properties"]["session"] == "sess-cmd"


def test_selected_session_file_is_the_last_resort(runner: CliRunner, data_dir: Path) -> None:
    """The file still wins over nothing, and still loses to an explicit value."""
    _select_database(data_dir, "alice")
    (data_dir / ".selected.session").write_text("sess-file")
    mock = MagicMock()
    mock.async_execute_query = AsyncMock(return_value=([], "sess-1"))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "query", "q"])
    assert result.exit_code == 0, result.output
    assert mock.async_execute_query.call_args.kwargs["optional_properties"]["session"] == "sess-file"


def test_data_query_top_k_is_forwarded(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.async_execute_query = AsyncMock(return_value=([], "sess-1"))
    with _patched(mock):
        _invoke(runner, data_dir, ["data", "query", "q", "--top-k", "5"])
    props = mock.async_execute_query.call_args.kwargs["optional_properties"]
    assert props["top_k"] == 5


def test_data_query_without_top_k_leaves_the_library_default(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.async_execute_query = AsyncMock(return_value=([], "sess-1"))
    with _patched(mock):
        _invoke(runner, data_dir, ["data", "query", "q"])
    assert "top_k" not in mock.async_execute_query.call_args.kwargs["optional_properties"]


def test_data_query_top_k_must_be_positive(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    result = _invoke(runner, data_dir, ["data", "query", "q", "--top-k", "0"])
    assert result.exit_code == 2


def test_data_query_error_exits_with_code_1(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.async_execute_query = AsyncMock(side_effect=QueryError("no db"))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "query", "q"])
    assert result.exit_code == 1


def test_data_search_returns_entities(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    result_row = SimpleNamespace(
        id="e1", type="ENTITY", name="Alice", description="a person",
        class_name="PERSON", head_name=None, relation_name=None, tail_name=None,
    )
    kb = _kb_source(search_data=[result_row])
    mock = _source_with_manager(_manager_with_kb(kb))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "search", "alice"])
    assert result.exit_code == 0
    assert "Alice" in result.output


def test_data_search_error_exits_with_code_1(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    kb = MagicMock()
    kb.search_data = AsyncMock(side_effect=Exception("boom"))
    mock = _source_with_manager(_manager_with_kb(kb))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "search", "alice"])
    assert result.exit_code == 1


def test_data_import_reports_success(runner: CliRunner, data_dir: Path, tmp_path: Path) -> None:
    _select_database(data_dir, "alice")
    input_file = tmp_path / "data.json"
    input_file.write_text(json.dumps({"nodes": []}))
    kb = _kb_source(import_database_data=None)
    mock = _source_with_manager(_manager_with_kb(kb))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "import", str(input_file)])
    assert result.exit_code == 0
    assert "Imported" in result.output


def test_data_import_invalid_json_exits_with_code_1(
    runner: CliRunner, data_dir: Path, tmp_path: Path
) -> None:
    _select_database(data_dir, "alice")
    input_file = tmp_path / "bad.json"
    input_file.write_text("{not json")
    mock = MagicMock()
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "import", str(input_file)])
    assert result.exit_code == 1
    assert "Invalid JSON" in result.output


def test_data_export_writes_json_to_stdout(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    kb = _kb_source(export_database_data={"nodes": []})
    mock = _source_with_manager(_manager_with_kb(kb))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "export"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"nodes": []}


def test_data_extract_reports_completion(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    kb = _kb_source(import_text=None)
    mock = _source_with_manager(_manager_with_kb(kb))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "extract", "Alice knows Python."])
    assert result.exit_code == 0
    assert "Extraction complete" in result.output


# ── data source group ──────────────────────────────────────────────────────────

def test_source_add_ingests_file(runner: CliRunner, data_dir: Path, tmp_path: Path) -> None:
    _select_database(data_dir, "alice")
    resume = tmp_path / "resume.txt"
    resume.write_text("Python\nSQL\n")
    mock = MagicMock()
    mock.add_source = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "source", "add", str(resume)])
    assert result.exit_code == 0
    assert "Ingested source" in result.output


def test_source_add_with_queries_reports_extraction_count(
    runner: CliRunner, data_dir: Path, tmp_path: Path
) -> None:
    _select_database(data_dir, "alice")
    resume = tmp_path / "resume.txt"
    resume.write_text("Python\nSQL\n")
    mock = MagicMock()
    mock.add_source = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(
            runner, data_dir,
            ["data", "source", "add", str(resume), "--query", "Skills?", "--query", "Remote?"],
        )
    assert result.exit_code == 0
    assert "2" in result.output and "queries" in result.output
    props = mock.add_source.await_args.kwargs["optional_properties"]
    assert props["queries"] == ["Skills?", "Remote?"]


def test_source_add_missing_file_exits_with_code_2(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "source", "add", "/no/such/file.txt"])
    assert result.exit_code == 2


_SOURCES = [
    {"id": "s1", "name": "resume", "source": "/home/a/resume.txt", "description": "CV",
     "original": None, "created": "2026-10-01T00:00:00+00:00", "modified": "2026-10-01T00:00:00+00:00"},
]


def test_source_list_shows_each_source_with_its_id(runner: CliRunner, data_dir: Path) -> None:
    """#149: no "(*)" marker — since #95 no source is in the registry, so it marked every one."""
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_sources = AsyncMock(return_value=_SOURCES)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "source", "list"])
    assert result.exit_code == 0, result.output
    assert "resume" in result.output and "s1" in result.output
    assert "(*)" not in result.output
    mock.list_sources.assert_awaited_once_with("alice")


def test_source_list_json_has_no_registry_flag(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_sources = AsyncMock(return_value=_SOURCES)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "source", "list", "--format", "json"])
    assert result.exit_code == 0, result.output
    [row] = json.loads(result.output)
    assert row["id"] == "s1" and row["name"] == "resume" and row["location"] == "/home/a/resume.txt"
    assert "in_registry" not in row


def test_source_list_empty(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_sources = AsyncMock(return_value=[])
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "source", "list"])
    assert result.exit_code == 0
    assert "(no sources)" in result.output


def test_source_remove_removes_and_reports_the_chunks(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_sources = AsyncMock(return_value=[{"id": "s1", "name": "resume.txt"}])
    mock.remove_source = AsyncMock(return_value={"id": "s1", "name": "resume.txt", "chunks_removed": 4})
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "source", "remove", "resume.txt", "--yes"])
    assert result.exit_code == 0, result.output
    mock.remove_source.assert_awaited_once_with("alice", "resume.txt")
    assert "Removed source: resume.txt (4 document chunks)" in result.output


def test_source_remove_accepts_an_id(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_sources = AsyncMock(return_value=[{"id": "s1", "name": "resume.txt"}])
    mock.remove_source = AsyncMock(return_value={"id": "s1", "name": "resume.txt", "chunks_removed": 1})
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "source", "remove", "s1", "--yes"])
    assert result.exit_code == 0, result.output
    mock.remove_source.assert_awaited_once_with("alice", "s1")


def test_source_remove_warns_when_chunks_cannot_be_located(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_sources = AsyncMock(return_value=[{"id": "s1", "name": "old.txt"}])
    mock.remove_source = AsyncMock(return_value={"id": "s1", "name": "old.txt", "chunks_removed": None})
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "source", "remove", "old.txt", "--yes"])
    assert result.exit_code == 0, result.output
    assert "could not be" in result.output and "database reset" in result.output


def test_source_remove_unknown_source_errors(runner: CliRunner, data_dir: Path) -> None:
    """Checked before the confirmation prompt, so a wrong name asks nothing."""
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_sources = AsyncMock(return_value=[{"id": "s1", "name": "resume.txt"}])
    mock.remove_source = AsyncMock()
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "source", "remove", "nonexistent"])
    assert result.exit_code == 1
    assert "No source 'nonexistent'" in result.output
    mock.remove_source.assert_not_awaited()


# ── schema group ───────────────────────────────────────────────────────────────

def _create_real_database(runner: CliRunner, data_dir: Path, *extra: str) -> None:
    """A real file-backed database, so the KB below is the real one, not a mock (#166)."""
    result = _invoke(runner, data_dir, [*extra, "database", "create", "alice", "--no-onboard"])
    assert result.exit_code == 0, result.output


def test_schema_list_shows_classes(runner: CliRunner, data_dir: Path) -> None:
    _create_real_database(runner, data_dir)
    result = _invoke(runner, data_dir, ["schema", "list"])
    assert result.exit_code == 0, result.output
    assert "Classes" in result.output
    assert "PERSON" in result.output
    assert "Class Hierarchy" in result.output  # USER is a subclass of PERSON


def test_schema_list_json_is_the_kb_schema(runner: CliRunner, data_dir: Path) -> None:
    """kb-source returns DataSchema.to_json()'s dict; the CLI prints it unchanged."""
    _create_real_database(runner, data_dir)
    result = _invoke(runner, data_dir, ["schema", "list", "--format", "json"])
    assert result.exit_code == 0, result.output
    schema = json.loads(result.output)
    assert "PERSON" in schema["entities"]
    assert set(schema) >= {"entities", "relations"}


def test_schema_list_empty_shows_placeholder(
    runner: CliRunner, data_dir: Path, tmp_path: Path
) -> None:
    empty = tmp_path / "empty_schema.json"
    empty.write_text(json.dumps({"entities": {}, "relations": {}}))
    _create_real_database(runner, data_dir, "--schema-path", str(empty))
    result = _invoke(runner, data_dir, ["schema", "list"])
    assert result.exit_code == 0, result.output
    assert "no schema declared" in result.output


def test_schema_import_reports_success(
    runner: CliRunner, data_dir: Path, tmp_path: Path
) -> None:
    _select_database(data_dir, "alice")
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps({"entities": {}, "relations": {}}))
    kb = _kb_source(import_database_schema=None)
    mock = _source_with_manager(_manager_with_kb(kb))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["schema", "import", str(schema_file)])
    assert result.exit_code == 0
    assert "Imported schema" in result.output


def test_schema_export_writes_json(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    kb = _kb_source(export_database_schema={"entities": {}, "relations": {}})
    mock = _source_with_manager(_manager_with_kb(kb))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["schema", "export"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"entities": {}, "relations": {}}


def test_schema_search_returns_matches(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    hit = SimpleNamespace(id="c1", type="CLASS", name="PERSON", description="A person")
    kb = _kb_source(search_schema=[hit])
    mock = _source_with_manager(_manager_with_kb(kb))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["schema", "search", "person"])
    assert result.exit_code == 0
    assert "PERSON" in result.output


def test_schema_search_type_is_lowercase_like_every_other_choice(
    runner: CliRunner, data_dir: Path
) -> None:
    """`--type` was the CLI's only uppercase Choice; `data search --type` and the
    other 20 are lowercase. The KB still receives the uppercase wire value."""
    _select_database(data_dir, "alice")
    kb = _kb_source(search_schema=[])
    mock = _source_with_manager(_manager_with_kb(kb))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["schema", "search", "person", "--type", "class"])
    assert result.exit_code == 0
    assert kb.search_schema.await_args.kwargs["type_filter"] == ["CLASS"]


def test_schema_search_type_still_accepts_uppercase(
    runner: CliRunner, data_dir: Path
) -> None:
    """case_sensitive=False keeps the old spelling working for anyone scripted
    against it."""
    _select_database(data_dir, "alice")
    kb = _kb_source(search_schema=[])
    mock = _source_with_manager(_manager_with_kb(kb))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["schema", "search", "person", "--type", "CLASS"])
    assert result.exit_code == 0
    assert kb.search_schema.await_args.kwargs["type_filter"] == ["CLASS"]


# ── metadata group ─────────────────────────────────────────────────────────────

def test_metadata_list_shows_categories(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_metadata.return_value = {"identity": {"name": "Alice"}}
    with _patched(mock):
        result = _invoke(runner, data_dir, ["metadata", "list"])
    assert result.exit_code == 0
    assert "identity" in result.output


def test_metadata_list_recursive_flattens_keys(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_metadata.return_value = {"identity": {"name": "Alice"}}
    with _patched(mock):
        result = _invoke(runner, data_dir, ["metadata", "list", "--recursive"])
    assert result.exit_code == 0
    assert "identity.name" in result.output
    assert "Alice" in result.output


def test_metadata_get_prints_value(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.get_metadata.return_value = "Alice"
    with _patched(mock):
        result = _invoke(runner, data_dir, ["metadata", "get", "identity", "name"])
    assert result.exit_code == 0
    assert "Alice" in result.output
    mock.get_metadata.assert_called_once_with("alice", "identity.name")


def test_metadata_get_unset_key_exits_with_code_1(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.get_metadata.return_value = None
    with _patched(mock):
        result = _invoke(runner, data_dir, ["metadata", "get", "identity", "name"])
    assert result.exit_code == 1
    assert "Not set" in result.output


def test_metadata_set_string_value(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    with _patched(mock):
        result = _invoke(runner, data_dir, ["metadata", "set", "identity", "name", "Alice"])
    assert result.exit_code == 0
    mock.set_metadata.assert_called_once_with("alice", "identity.name", "Alice")


def test_metadata_set_parses_json_value(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    with _patched(mock):
        result = _invoke(
            runner, data_dir,
            ["metadata", "set", "privacy", "sensitive_categories", '["health", "financial"]'],
        )
    assert result.exit_code == 0
    mock.set_metadata.assert_called_once_with(
        "alice", "privacy.sensitive_categories", ["health", "financial"]
    )


def test_metadata_delete_confirmed(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    with _patched(mock):
        result = _invoke(runner, data_dir, ["metadata", "delete", "identity", "pronouns", "--yes"])
    assert result.exit_code == 0
    mock.delete_metadata.assert_called_once_with("alice", "identity.pronouns")


# ── contact group ──────────────────────────────────────────────────────────────

def test_contact_list_shows_protocols_with_entries(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    manager = MagicMock()
    manager.get_contacts.return_value = {"email": {"work": {"address": "a@example.com"}}}
    mock = _source_with_manager(manager)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["contact", "list"])
    assert result.exit_code == 0
    assert "email" in result.output


def test_contact_get_returns_field_value(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    manager = MagicMock()
    manager.get_contact.return_value = {"address": "a@example.com"}
    mock = _source_with_manager(manager)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["contact", "get", "email", "work", "address"])
    assert result.exit_code == 0
    assert "a@example.com" in result.output


def test_contact_get_requires_protocol_and_name(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    with _patched(mock):
        result = _invoke(runner, data_dir, ["contact", "get", "email"])
    assert result.exit_code == 1
    assert "protocol and name" in result.output


def test_contact_set_updates_field(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    manager = MagicMock()
    mock = _source_with_manager(manager)
    with _patched(mock):
        result = _invoke(
            runner, data_dir,
            ["contact", "set", "sms", "primary", "phone", "+15550123"],
        )
    assert result.exit_code == 0
    manager.set_contact_field.assert_called_once_with("sms", "primary", "phone", "+15550123")


def test_contact_add_creates_entry(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    manager = MagicMock()
    manager.get_contact.return_value = None
    mock = _source_with_manager(manager)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["contact", "add", "sms", "primary"])
    assert result.exit_code == 0
    assert "Added" in result.output


def test_contact_add_duplicate_exits_with_code_1(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    manager = MagicMock()
    manager.get_contact.return_value = {"preference": 0}
    mock = _source_with_manager(manager)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["contact", "add", "sms", "primary"])
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_contact_add_unknown_protocol_exits_with_code_1(
    runner: CliRunner, data_dir: Path
) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    with _patched(mock):
        result = _invoke(runner, data_dir, ["contact", "add", "carrier_pigeon", "primary"])
    assert result.exit_code == 1
    assert "Unknown protocol" in result.output


def test_contact_remove_confirmed(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    manager = MagicMock()
    mock = _source_with_manager(manager)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["contact", "remove", "sms", "primary", "--yes"])
    assert result.exit_code == 0
    manager.delete_contact.assert_called_once_with("sms", "primary")




# ── error reporting ────────────────────────────────────────────────────────────

def test_json_format_errors_are_json(runner: CliRunner, data_dir: Path) -> None:
    """A caller parsing --format json output needs something parseable when the
    command fails, not a plain-text line."""
    mock = MagicMock()
    mock.list_users.return_value = []
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "list", "--format", "json"])
    assert result.exit_code == 1
    assert "No database selected" in json.loads(result.output)["error"]


def test_plain_format_errors_stay_human_readable(runner: CliRunner, data_dir: Path) -> None:
    mock = MagicMock()
    mock.list_users.return_value = []
    with _patched(mock):
        result = _invoke(runner, data_dir, ["data", "list"])
    assert result.exit_code == 1
    assert result.output.startswith("Error:")


def test_session_start_failure_reports_cleanly(runner: CliRunner, data_dir: Path) -> None:
    """session start called asyncio.run unguarded, so a library exception reached
    the user as a traceback where every other command caught it."""
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.create_session = AsyncMock(side_effect=RuntimeError("backend is down"))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["session", "start"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "backend is down" in result.output


def test_session_show_failure_reports_cleanly(runner: CliRunner, data_dir: Path) -> None:
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.get_session = AsyncMock(side_effect=RuntimeError("backend is down"))
    with _patched(mock):
        result = _invoke(runner, data_dir, ["session", "show", "sess-1"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output

# ── configurable metadata/contact schemas ──────────────────────────────────────

def _write_schema(tmp_path: Path, name: str, doc: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(doc))
    return path


def test_metadata_list_defaults_to_the_packaged_schema(
    runner: CliRunner, data_dir: Path
) -> None:
    """With nothing configured, the schema shipped with the library is used."""
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_metadata.return_value = {}
    with _patched(mock):
        result = _invoke(runner, data_dir, ["metadata", "list"])
    assert result.exit_code == 0
    assert "identity" in result.output


def test_metadata_list_uses_the_configured_schema(
    runner: CliRunner, data_dir: Path, tmp_path: Path
) -> None:
    schema = _write_schema(tmp_path, "metadata_schema.json", {"spaceflight": {"callsign": None}})
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_metadata.return_value = {}
    with _patched(mock):
        result = runner.invoke(cli, [
            "--data-dir", str(data_dir),
            "--metadata-schema-path", str(schema),
            "metadata", "list",
        ])
    assert result.exit_code == 0, result.output
    assert "spaceflight" in result.output
    assert "identity" not in result.output


def test_contact_list_uses_the_configured_schema(
    runner: CliRunner, data_dir: Path, tmp_path: Path
) -> None:
    schema = _write_schema(tmp_path, "contact_schema.json", {"carrier_pigeon": {"loft": None}})
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_contacts.return_value = {}
    with _patched(mock):
        result = runner.invoke(cli, [
            "--data-dir", str(data_dir),
            "--contact-schema-path", str(schema),
            "contact", "list",
        ])
    assert result.exit_code == 0, result.output
    assert "carrier_pigeon" in result.output


def test_an_unreadable_schema_warns_and_falls_back_to_the_packaged_copy(
    runner: CliRunner, data_dir: Path, tmp_path: Path
) -> None:
    """A broken schema degrades to the packaged one rather than emptying the CLI."""
    schema = tmp_path / "broken_metadata_schema.json"
    schema.write_text("{ not json")
    _select_database(data_dir, "alice")
    mock = MagicMock()
    mock.list_metadata.return_value = {}
    with _patched(mock):
        result = runner.invoke(cli, [
            "--data-dir", str(data_dir),
            "--metadata-schema-path", str(schema),
            "metadata", "list",
        ])
    assert result.exit_code == 0, result.output
    assert "Warning" in result.output
    assert "identity" in result.output


def test_database_create_registers_the_configured_schema_paths(
    runner: CliRunner, data_dir: Path, tmp_path: Path
) -> None:
    """The seeding commands hand the paths to the source, which stores them."""
    metadata_schema = _write_schema(tmp_path, "metadata_schema.json", {"spaceflight": {}})
    contact_schema = _write_schema(tmp_path, "contact_schema.json", {"carrier_pigeon": {}})
    mock = MagicMock()
    mock.list_users.return_value = []
    mock.create_user = AsyncMock(return_value=None)
    mock.onboard_user = AsyncMock(return_value=None)
    with patch("blue_data_user_cli.commands._make_source", return_value=mock) as make_source:
        result = runner.invoke(cli, [
            "--data-dir", str(data_dir),
            "--metadata-schema-path", str(metadata_schema),
            "--contact-schema-path", str(contact_schema),
            "database", "create", "alice", "--no-onboard", "--no-metadata-onboard",
        ])
    assert result.exit_code == 0, result.output
    args = make_source.call_args.args
    assert str(metadata_schema) in [str(a) for a in args]
    assert str(contact_schema) in [str(a) for a in args]


def test_contact_get_and_list_mask_secrets(runner: CliRunner, data_dir: Path) -> None:
    """#143: the SMTP password is never printed; a $VAR reference is."""
    _select_database(data_dir, "alice")
    mock = MagicMock()
    stored = {"address": "a@example.com", "smtp_password": "hunter2", "smtp_user": "$SMTP_USER"}
    mock._get_manager.return_value.get_contact.return_value = stored
    mock._get_manager.return_value.get_contacts.return_value = {"email": {"work": stored}}
    with _patched(mock):
        entry = _invoke(runner, data_dir, ["contact", "get", "email", "work"])
        field = _invoke(runner, data_dir, ["contact", "get", "email", "work", "smtp_password"])
        listed = _invoke(runner, data_dir, ["contact", "list", "email", "work", "--format", "json"])
    for result in (entry, field, listed):
        assert result.exit_code == 0, result.output
        assert "hunter2" not in result.output
    assert "***" in field.output
    assert "a@example.com" in entry.output


def test_neo4j_password_comes_from_the_profile(runner: CliRunner, data_dir: Path) -> None:
    """#104: a secret must not be required on the command line, where shell history keeps it."""
    configured = runner.invoke(
        cli, ["--data-dir", str(data_dir), "profile", "config", "BLUE_DATA_USER_SOURCE_NEO4J_PASSWORD"], input="s3cret\n"
    )
    assert configured.exit_code == 0, configured.output
    mock = MagicMock()
    mock.list_users.return_value = []
    mock.create_user = AsyncMock(return_value=None)
    mock.onboard_user = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "create", "alice", "--kb-backend", "neo4j", "--no-onboard"])
    assert result.exit_code == 0, result.output
    assert mock.create_user.await_args.args[2]["connection"]["password"] == "s3cret"
    inspected = _invoke(runner, data_dir, ["profile", "inspect"])
    assert "s3cret" not in inspected.output


def test_version(runner: CliRunner) -> None:
    from importlib.metadata import version

    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"blue-userdb, version {version('blue-data-user-cli')}"


def test_database_create_skips_onboarding_without_a_terminal(runner: CliRunner, data_dir: Path) -> None:
    """#104: under a pipe the interview would read EOF and record blank answers."""
    mock = MagicMock()
    mock.list_users.return_value = []
    mock.create_user = AsyncMock(return_value=None)
    mock.onboard_user = AsyncMock(return_value=None)
    with _patched(mock):
        result = _invoke(runner, data_dir, ["database", "create", "alice"])  # CliRunner stdin is not a TTY
    assert result.exit_code == 0, result.output
    assert "Created database: alice" in result.output
    text = " ".join(result.output.split())  # Rich wraps long lines
    assert "skipped onboarding" in text and "database onboard" in text
    mock.onboard_user.assert_not_called()


def test_neo4j_password_is_not_a_command_line_option(runner: CliRunner, data_dir: Path) -> None:
    """ADR-026: a password on the command line lands in shell history."""
    result = _invoke(runner, data_dir, ["database", "create", "alice", "--kb-backend", "neo4j",
                                        "--neo4j-password", "s3cret", "--no-onboard"])
    assert result.exit_code == 2
    assert "No such option" in result.output
