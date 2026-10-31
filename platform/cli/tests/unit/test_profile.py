"""`blue-userdb profile` — the command group, and the configuration it drives.

Mirrors `blue_data_kb_cli`'s test_profile.py: the CLI checklist requires
`profile` to behave identically across the family, so the two suites are meant
to assert the same things.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from blue_data_user_cli.commands import cli
from blue_data_user_cli.profile import cli_spec


def _run(runner, data_dir: Path, args: list[str]):
    result = runner.invoke(cli, ["--data-dir", str(data_dir), *args])
    assert result.exit_code == 0, result.output
    return result


def _json(runner, data_dir: Path, args: list[str]):
    return json.loads(_run(runner, data_dir, args).output)


# ------------------------------------------------------------------ #
# spec                                                                #
# ------------------------------------------------------------------ #

def test_spec_merges_family_parameters_with_this_cli_s_own():
    spec = cli_spec()
    assert "OPENAI_API_KEY" in spec                        # family
    assert "BLUE_DATA_CLI_LOG_LIMIT" in spec               # family
    assert "BLUE_DATA_USER_SOURCE_DATA_DIR" in spec        # this CLI
    assert "BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL" in spec


def test_first_run_asks_only_three_questions():
    """blue-data 1.0 made BLUE_DATA_LLM_MODEL optional (blank = the provider's default)."""
    assert [p.name for p in cli_spec().required()] == [
        "OPENAI_API_KEY",
        "BLUE_DATA_USER_SOURCE_DATA_DIR",
        "BLUE_DATA_USER_SOURCE_DATABASE",
    ]


def test_both_llm_models_inherit_toward_the_family_model():
    """The calls go to the family provider (#190), so its model applies again."""
    spec = cli_spec()
    assert spec["BLUE_DATA_USER_SOURCE_LLM_MODEL"].inherits == ("BLUE_DATA_LLM_MODEL",)
    for fn in ("EXTRACTION", "REASONING"):
        param = spec[f"BLUE_DATA_USER_SOURCE_{fn}_LLM_MODEL"]
        assert param.inherits == ("BLUE_DATA_USER_SOURCE_LLM_MODEL", "BLUE_DATA_LLM_MODEL")


def test_database_creation_defaults_are_declared():
    """`blue-userdb database create` has no `database config set` to change these after
    the fact, so the profile is the only place a per-environment default can
    live."""
    spec = cli_spec()
    for name in ("KB_BACKEND", "KB_SEARCH_MODE", "KB_VECTOR_BACKEND",
                 "KB_EMBEDDING_MODEL", "DOC_BACKEND",
                 "NEO4J_HOST", "NEO4J_PORT", "NEO4J_USER"):
        assert f"BLUE_DATA_USER_SOURCE_{name}" in spec


# ------------------------------------------------------------------ #
# first use                                                           #
# ------------------------------------------------------------------ #

def test_the_first_command_creates_the_default_profile(runner, data_dir):
    assert not (data_dir / ".profiles").exists()
    out = _json(runner, data_dir, ["profile", "list", "--format", "json"])
    assert out == {"selected": "default", "profiles": ["default"]}


def test_the_created_profile_is_empty_so_values_track_spec_defaults(runner, data_dir, monkeypatch):
    monkeypatch.delenv("BLUE_DATA_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("BLUE_DATA_LLM_MODEL", raising=False)
    out = _json(runner, data_dir, ["profile", "inspect", "--format", "json"])
    # Unset, so the commands use the provider's default, and inspect says which (#190).
    assert out["values"]["BLUE_DATA_LLM_MODEL"] == {"value": "gpt-4o", "source": "openai default"}


def test_a_removed_default_profile_is_not_resurrected(runner, data_dir):
    _run(runner, data_dir, ["profile", "add", "staging"])
    _run(runner, data_dir, ["profile", "select", "staging"])
    _run(runner, data_dir, ["profile", "remove", "default", "--confirm"])
    assert _json(runner, data_dir, ["profile", "list", "--format", "json"])["profiles"] == ["staging"]


# ------------------------------------------------------------------ #
# add / list / select / remove                                        #
# ------------------------------------------------------------------ #

def test_add_and_select_change_the_active_profile(runner, data_dir):
    _run(runner, data_dir, ["profile", "add", "staging"])
    _run(runner, data_dir, ["profile", "select", "staging"])
    out = _json(runner, data_dir, ["profile", "list", "--format", "json"])
    assert out["selected"] == "staging"
    assert set(out["profiles"]) == {"default", "staging"}


def test_selecting_an_unknown_profile_fails_cleanly(runner, data_dir):
    result = runner.invoke(cli, ["--data-dir", str(data_dir), "profile", "select", "ghost"])
    assert result.exit_code != 0
    assert "no such profile" in result.output


def test_remove_requires_confirmation(runner, data_dir):
    _run(runner, data_dir, ["profile", "add", "staging"])
    result = runner.invoke(
        cli, ["--data-dir", str(data_dir), "profile", "remove", "staging"], input="n\n"
    )
    assert result.exit_code != 0
    assert "staging" in _json(runner, data_dir, ["profile", "list", "--format", "json"])["profiles"]


# ------------------------------------------------------------------ #
# config                                                              #
# ------------------------------------------------------------------ #

def test_config_with_param_and_value_sets_it(runner, data_dir):
    _run(runner, data_dir, ["profile", "config", "BLUE_DATA_LLM_MODEL", "gpt-5"])
    assert "gpt-5" in (data_dir / ".profiles").read_text()


def test_config_with_only_a_param_prompts(runner, data_dir):
    result = runner.invoke(
        cli, ["--data-dir", str(data_dir), "profile", "config", "BLUE_DATA_LLM_MODEL"],
        input="gpt-5\n",
    )
    assert result.exit_code == 0, result.output
    assert "gpt-5" in (data_dir / ".profiles").read_text()


def test_config_rejects_an_unknown_parameter(runner, data_dir):
    result = runner.invoke(
        cli, ["--data-dir", str(data_dir), "profile", "config", "NOT_A_PARAM", "x"]
    )
    assert result.exit_code != 0
    assert "unknown configuration parameter" in result.output


def test_config_validates_against_the_cast(runner, data_dir):
    result = runner.invoke(
        cli, ["--data-dir", str(data_dir), "profile", "config",
              "BLUE_DATA_USER_SOURCE_NEO4J_PORT", "not-a-number"]
    )
    assert result.exit_code != 0
    assert "BLUE_DATA_USER_SOURCE_NEO4J_PORT" in result.output


# ------------------------------------------------------------------ #
# secrets                                                             #
# ------------------------------------------------------------------ #

def test_a_secret_cannot_be_passed_on_the_command_line(runner, data_dir):
    result = runner.invoke(
        cli, ["--data-dir", str(data_dir), "profile", "config", "OPENAI_API_KEY", "sk-leaked"]
    )
    assert result.exit_code != 0
    assert "shell history" in result.output


def test_a_prompted_secret_is_not_stored_in_the_clear(runner, data_dir):
    result = runner.invoke(
        cli, ["--data-dir", str(data_dir), "profile", "config", "OPENAI_API_KEY"],
        input="sk-secret-value\n",
    )
    assert result.exit_code == 0, result.output
    stored = (data_dir / ".profiles").read_text()
    assert "sk-secret-value" not in stored
    assert "enc:" in stored


def test_inspect_masks_a_stored_secret(runner, data_dir):
    runner.invoke(
        cli, ["--data-dir", str(data_dir), "profile", "config", "OPENAI_API_KEY"],
        input="sk-secret-value\n",
    )
    out = _run(runner, data_dir, ["profile", "inspect", "--format", "json"]).output
    assert "sk-secret-value" not in out
    assert "***" in out


def test_a_secret_can_reference_an_environment_variable(runner, data_dir, monkeypatch):
    runner.invoke(
        cli, ["--data-dir", str(data_dir), "profile", "config", "OPENAI_API_KEY"],
        input="$MY_KEY\n",
    )
    out = _json(runner, data_dir, ["profile", "inspect", "--format", "json"])
    assert out["values"]["OPENAI_API_KEY"]["value"] == "$MY_KEY (unset)"

    monkeypatch.setenv("MY_KEY", "sk-live")
    out = _json(runner, data_dir, ["profile", "inspect", "--format", "json"])
    assert out["values"]["OPENAI_API_KEY"]["value"] == "$MY_KEY (set)"


# ------------------------------------------------------------------ #
# precedence                                                          #
# ------------------------------------------------------------------ #

def test_inspect_reports_where_each_value_came_from(runner, data_dir, monkeypatch):
    _run(runner, data_dir, ["profile", "config", "BLUE_DATA_LLM_MODEL", "from-profile"])
    out = _json(runner, data_dir, ["profile", "inspect", "--format", "json"])
    assert out["values"]["BLUE_DATA_LLM_MODEL"] == {
        "value": "from-profile", "source": "profile:default",
    }

    monkeypatch.setenv("BLUE_DATA_LLM_MODEL", "from-env")
    out = _json(runner, data_dir, ["profile", "inspect", "--format", "json"])
    assert out["values"]["BLUE_DATA_LLM_MODEL"] == {
        "value": "from-env", "source": "environment",
    }


def test_a_specific_model_falls_back_to_the_udb_wide_one(runner, data_dir):
    _run(runner, data_dir, ["profile", "config", "BLUE_DATA_USER_SOURCE_LLM_MODEL", "blue-userdb-wide"])
    out = _json(runner, data_dir, ["profile", "inspect", "--format", "json"])
    assert out["values"]["BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL"]["value"] == "blue-userdb-wide"

    _run(runner, data_dir, [
        "profile", "config", "BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL", "reasoning-only",
    ])
    out = _json(runner, data_dir, ["profile", "inspect", "--format", "json"])
    assert out["values"]["BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL"]["value"] == "reasoning-only"
    assert out["values"]["BLUE_DATA_USER_SOURCE_EXTRACTION_LLM_MODEL"]["value"] == "blue-userdb-wide"


def test_the_profile_supplies_the_data_dir(runner, data_dir, tmp_path, monkeypatch):
    """With nothing exported, the profile's value is the one that resolves."""
    elsewhere = tmp_path / "from-profile"
    _run(runner, data_dir, [
        "profile", "config", "BLUE_DATA_USER_SOURCE_DATA_DIR", str(elsewhere),
    ])
    monkeypatch.delenv("BLUE_DATA_USER_SOURCE_DATA_DIR", raising=False)
    out = _json(runner, data_dir, ["profile", "inspect", "--format", "json"])
    assert out["values"]["BLUE_DATA_USER_SOURCE_DATA_DIR"] == {
        "value": str(elsewhere), "source": "profile:default",
    }


def test_the_data_dir_option_outranks_the_profile(runner, data_dir, tmp_path, monkeypatch):
    """--data-dir is tier 1, and every existing test relies on it. Asserted on
    where a write actually lands, not on what `inspect` reports."""
    elsewhere = tmp_path / "from-profile"
    elsewhere.mkdir(parents=True, exist_ok=True)
    _run(runner, data_dir, [
        "profile", "config", "BLUE_DATA_USER_SOURCE_DATA_DIR", str(elsewhere),
    ])
    monkeypatch.delenv("BLUE_DATA_USER_SOURCE_DATA_DIR", raising=False)

    with patch("blue_data_user_cli.commands._make_source") as make_source:
        make_source.return_value.list_users.return_value = ["alice"]
        result = runner.invoke(
            cli, ["--data-dir", str(data_dir), "database", "select", "alice"]
        )
    assert result.exit_code == 0, result.output
    assert (data_dir / ".selected.database").read_text() == "alice"
    assert not (elsewhere / ".selected.database").exists()


def test_profile_commands_do_not_create_a_database(runner, data_dir):
    _run(runner, data_dir, ["profile", "list"])
    _run(runner, data_dir, ["profile", "config", "BLUE_DATA_LLM_MODEL", "gpt-4o"])
    assert (data_dir / ".profiles").exists()
    assert not (data_dir / "registry.json").exists()


def test_the_schema_paths_are_optional_file_parameters():
    """All three seeding schemas are configurable, and none is asked for on
    first run — each falls back to the copy packaged with the library."""
    spec = cli_spec()
    for name in (
        "BLUE_DATA_USER_SOURCE_SCHEMA_PATH",
        "BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH",
        "BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH",
    ):
        assert name in spec
        assert spec[name].cast == "file"
        assert spec[name].required is False


def test_the_metadata_schema_path_comes_from_the_profile(runner, data_dir, tmp_path, monkeypatch):
    schema = tmp_path / "metadata_schema.json"
    schema.write_text("{}")
    _run(runner, data_dir, [
        "profile", "config", "BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH", str(schema),
    ])
    monkeypatch.delenv("BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH", raising=False)
    out = _json(runner, data_dir, ["profile", "inspect", "--format", "json"])
    assert out["values"]["BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH"] == {
        "value": str(schema), "source": "profile:default",
    }


# ------------------------------------------------------------------ #
# which database commands act on (#121)                               #
# ------------------------------------------------------------------ #

def _db_used(runner, data_dir: Path, args: list[str] = ()) -> str:
    """The database `metadata get` reads from, with the library stubbed out."""
    with patch("blue_data_user_cli.commands._make_source") as make_source:
        make_source.return_value.get_metadata.return_value = "x"
        _run(runner, data_dir, [*args, "metadata", "get", "identity", "name"])
    return make_source.return_value.get_metadata.call_args.args[0]


def _marked(runner, data_dir: Path) -> list[str]:
    """The databases `database list` marks as selected."""
    with patch("blue_data_user_cli.commands._make_source") as make_source:
        make_source.return_value.list_users.return_value = ["alice", "bob"]
        make_source.return_value.get_user.return_value = {}
        rows = _json(runner, data_dir, ["database", "list", "--format", "json"])
    return [r["name"] for r in rows if r["selected"]]


def test_the_selection_outranks_the_profile_s_database(runner, data_dir):
    """`database select` (and `database create`) must win over a profile value,
    or every command silently acts on the profile's database while `list` marks
    another."""
    _run(runner, data_dir, ["profile", "config", "BLUE_DATA_USER_SOURCE_DATABASE", "alice"])
    (data_dir / ".selected.database").write_text("bob")
    assert _db_used(runner, data_dir) == "bob"
    assert _marked(runner, data_dir) == ["bob"]


def test_the_profile_s_database_applies_when_nothing_is_selected(runner, data_dir):
    _run(runner, data_dir, ["profile", "config", "BLUE_DATA_USER_SOURCE_DATABASE", "alice"])
    assert _db_used(runner, data_dir) == "alice"
    assert _marked(runner, data_dir) == ["alice"]


def test_an_exported_database_outranks_the_selection(runner, data_dir, monkeypatch):
    (data_dir / ".selected.database").write_text("bob")
    monkeypatch.setenv("BLUE_DATA_USER_SOURCE_DATABASE", "alice")
    assert _db_used(runner, data_dir) == "alice"
    assert _marked(runner, data_dir) == ["alice"]


def test_the_database_option_outranks_everything(runner, data_dir, monkeypatch):
    _run(runner, data_dir, ["profile", "config", "BLUE_DATA_USER_SOURCE_DATABASE", "alice"])
    (data_dir / ".selected.database").write_text("bob")
    monkeypatch.setenv("BLUE_DATA_USER_SOURCE_DATABASE", "carol")
    assert _db_used(runner, data_dir, ["--database", "dave"]) == "dave"


# ------------------------------------------------------------------ #
# the model, a model of the BLUE_DATA_LLM_PROVIDER provider (#190)   #
# ------------------------------------------------------------------ #

def _model(data_dir: Path, function: str = "REASONING", option: str | None = None) -> str:
    from blue_data_user_cli.commands import _model_for
    from blue_data_user_cli.profile import resolver_for
    return _model_for({"config": resolver_for(str(data_dir))}, function, option)


def test_the_family_model_is_used_under_any_provider(data_dir, monkeypatch):
    for provider, model in (("", "gpt-5"), ("openai", "gpt-5"), ("anthropic", "claude-sonnet-4-8")):
        monkeypatch.setenv("BLUE_DATA_LLM_PROVIDER", provider)
        monkeypatch.setenv("BLUE_DATA_LLM_MODEL", model)
        assert _model(data_dir) == model
        assert _model(data_dir, "EXTRACTION") == model


def test_unset_the_providers_default_is_used(data_dir, monkeypatch):
    monkeypatch.delenv("BLUE_DATA_LLM_MODEL", raising=False)
    for provider, model in (("", "gpt-4o"), ("OpenAI", "gpt-4o"), ("anthropic", "claude-opus-4-8")):
        monkeypatch.setenv("BLUE_DATA_LLM_PROVIDER", provider)
        assert _model(data_dir) == model
        assert _model(data_dir, "EXTRACTION") == model


def test_profile_inspect_shows_the_providers_default_for_an_unset_model(runner, data_dir, monkeypatch):
    monkeypatch.delenv("BLUE_DATA_LLM_MODEL", raising=False)
    monkeypatch.setenv("BLUE_DATA_LLM_PROVIDER", "anthropic")
    values = _json(runner, data_dir, ["profile", "inspect", "--format", "json"])["values"]
    for name in ("BLUE_DATA_LLM_MODEL", "BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL"):
        assert values[name] == {"value": "claude-opus-4-8", "source": "anthropic default"}


def test_this_packages_model_and_the_option_win_over_any_provider(data_dir, monkeypatch):
    monkeypatch.setenv("BLUE_DATA_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("BLUE_DATA_LLM_MODEL", "claude-opus-4-8")
    monkeypatch.setenv("BLUE_DATA_USER_SOURCE_LLM_MODEL", "gpt-4.1")
    assert _model(data_dir) == "gpt-4.1"
    assert _model(data_dir, option="gpt-5") == "gpt-5"
