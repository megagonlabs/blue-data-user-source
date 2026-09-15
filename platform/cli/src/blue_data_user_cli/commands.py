from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from blue_data_user_source import FileUserSource, UDbError, sanitize_registry_name
from blue_data_user_source.data.manager import (
    CLS_JSON_FILE,
    CLS_JSON_MEMORY,
    CLS_KB_FILE,
    CLS_KB_MEMORY,
    CLS_KB_NEO4J,
    CLS_VECTOR_FILE,
    CLS_VECTOR_MEMORY,
)

_DEFAULT_DATA_DIR = Path.home() / ".udb"
_SELECTED_DB_FILE = ".selected.database"
_SELECTED_SESSION_FILE = ".selected.session"
_INTERNAL_SOURCES = {"kb", "metadata", "contacts", "sessions", "session_content", "external_documents"}

console = Console()
err = Console(stderr=True)


def _truncate(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _status_tool_callbacks(
    status: Any, label: str, verbose: bool = False, log: bool = False, log_limit: int = 80
) -> tuple[Any, Any]:
    def on_tool_call(name: str, args: dict) -> None:
        if not (verbose or log):
            return
        if verbose and args:
            args_str = _truncate(", ".join(f"{k}={v!r}" for k, v in args.items()), log_limit)
            detail = f"({name}: {args_str})"
        else:
            detail = f"({name})"
        status.update(f"{label}… [dim]{detail}[/dim]")
        if log:
            console.print(f"[dim]{label}… {detail}[/dim]")

    def on_tool_result(name: str, args: dict, result: Any) -> None:
        if not log:
            return
        result_str = _truncate(repr(result), log_limit)
        console.print(f"[dim]{label}… ({name}) -> {result_str}[/dim]")

    return on_tool_call, on_tool_result


def _humanize_date(iso_str: str | None) -> str:
    if not iso_str:
        return ""
    try:
        import arrow
        return arrow.get(iso_str).to("local").format("MMM D, YYYY h:mm A")
    except Exception:
        return iso_str


def _make_source(data_dir: Path, schema_path: Path | None = None) -> FileUserSource:
    data_dir.mkdir(parents=True, exist_ok=True)
    return FileUserSource("user_source", {
        "connection": {"path": str(data_dir / "registry.json")},
        "schema": str(schema_path) if schema_path else None,
    })


def _user_registry_props(data_dir: Path, name: str) -> dict:
    return {
        "_class": CLS_JSON_FILE,
        "connection": {
            "protocol": "json/file",
            "path": str(data_dir / "registries" / f"{name}.json"),
        },
    }


def _kb_search_props(
    data_dir: Path,
    name: str,
    kb_backend: str,
    kb_search_mode: str,
    kb_vector_backend: str,
    kb_embedding_model: str,
) -> dict:
    """Build the "search" block for a KB source's connection properties, driving the
    schema/data search index (used e.g. by extraction's search_schema/search_data
    tools, and entity/fact dedup) — without it, KBSource falls back to a much
    weaker exact-substring schema lookup. "none" omits the block entirely (no
    index built). "bm25" is keyword-only, no extra config needed. "semantic"
    additionally builds a vector index from kb_vector_backend/kb_embedding_model.

    For persistent kb_backend values ("file"/"neo4j"), the BM25 corpus is
    written under a directory of its own so it survives across CLI invocations
    (each `udb` command is a fresh process — an unpersisted, in-memory-only
    corpus would come back empty every time).
    """
    if kb_search_mode == "none":
        return {}
    search: dict[str, Any] = {"mode": kb_search_mode}
    if kb_backend in ("file", "neo4j"):
        search["bm25_index_dir"] = str(data_dir / "sources" / name / "kb_search_index")
    if kb_search_mode == "semantic":
        if kb_vector_backend == "file":
            vector_conn = {"directory": str(data_dir / "sources" / name / "kb_vectors")}
            vector_class = CLS_VECTOR_FILE
        else:
            vector_conn = {"protocol": "vector/memory"}
            vector_class = CLS_VECTOR_MEMORY
        search["vector"] = {"_class": vector_class, "connection": vector_conn}
        search["embedding"] = {"provider": "openai", "model": kb_embedding_model}
    return {"search": search}


def _user_kb_props(
    data_dir: Path,
    name: str,
    kb_backend: str,
    kb_search_mode: str = "bm25",
    kb_vector_backend: str = "file",
    kb_embedding_model: str = "text-embedding-3-small",
    **kb_extras: Any,
) -> dict:
    search_props = _kb_search_props(
        data_dir, name, kb_backend, kb_search_mode, kb_vector_backend, kb_embedding_model
    )
    if kb_backend == "file":
        return {
            "_class": CLS_KB_FILE,
            "connection": {
                "protocol": "kb/file",
                "directory": str(data_dir / "sources" / name),
            },
            **search_props,
        }
    if kb_backend == "memory":
        return {
            "_class": CLS_KB_MEMORY,
            "connection": {"protocol": "kb/memory"},
            **search_props,
        }
    if kb_backend == "neo4j":
        return {
            "_class": CLS_KB_NEO4J,
            "connection": {"protocol": "kb/neo4j", **kb_extras},
            **search_props,
        }
    raise ValueError(f"Unknown KB backend: {kb_backend!r}")


def _user_metadata_props(data_dir: Path, name: str) -> dict:
    return {
        "_class": CLS_JSON_FILE,
        "connection": {
            "protocol": "json/file",
            "path": str(data_dir / "sources" / name / "metadata.json"),
        },
    }


def _user_contact_props(data_dir: Path, name: str) -> dict:
    return {
        "_class": CLS_JSON_FILE,
        "connection": {
            "protocol": "json/file",
            "path": str(data_dir / "sources" / name / "contacts.json"),
        },
    }


def _user_session_props(data_dir: Path, name: str) -> dict:
    return {
        "_class": CLS_JSON_FILE,
        "connection": {
            "protocol": "json/file",
            "path": str(data_dir / "sources" / name / "sessions.json"),
        },
    }


def _user_doc_source_props(data_dir: Path, name: str, doc_backend: str) -> dict:
    """Config for per-session interaction-transcript DocumentDataSources.

    "memory" (default) doesn't persist ingested transcripts across CLI
    invocations (each command is a fresh process) — use "file" for that.
    """
    if doc_backend == "memory":
        return {"embedding_model": "dummy", "vector_source": {"backend": "memory"}}
    if doc_backend == "file":
        return {
            "embedding_model": "dummy",
            "vector_source": {"backend": "file", "directory": str(data_dir / "sources" / name / "sessions")},
        }
    raise ValueError(f"Unknown doc-source backend: {doc_backend!r}")


def _selected_db_path(data_dir: Path) -> Path:
    return data_dir / _SELECTED_DB_FILE


def _get_db(obj: dict) -> str:
    db = obj.get("database")
    if db:
        return db
    sel_path = _selected_db_path(obj["data_dir"])
    if sel_path.exists():
        db = sel_path.read_text().strip()
        if db:
            return db
    err.print("[red]Error:[/red] No database selected. Use --database or run 'udb database select NAME'.")
    sys.exit(1)


def _selected_session_path(data_dir: Path) -> Path:
    return data_dir / _SELECTED_SESSION_FILE


def _get_session(obj: dict, session: str | None) -> str | None:
    """Resolve a session id: --session flag → env var → .selected.session file → None.

    Unlike _get_db, an unresolved session is NOT an error — None means the
    caller should let the query auto-create a new session (reuse-or-create).
    """
    if session:
        return session
    import os
    env_session = os.environ.get("BLUE_DATA_USER_SOURCE_SESSION")
    if env_session:
        return env_session
    sel_path = _selected_session_path(obj["data_dir"])
    if sel_path.exists():
        sel = sel_path.read_text().strip()
        if sel:
            return sel
    return None


# ------------------------------------------------------------------ #
# Root CLI                                                            #
# ------------------------------------------------------------------ #

@click.group()
@click.option(
    "--database",
    envvar="BLUE_DATA_USER_SOURCE_DATABASE",
    default=None,
    help="Database (user) name. Overrides BLUE_DATA_USER_SOURCE_DATABASE env var.",
)
@click.option(
    "--data-dir",
    envvar="BLUE_DATA_USER_SOURCE_DATA_DIR",
    default=str(_DEFAULT_DATA_DIR),
    show_default=True,
    help="Directory where user data is stored. Overrides BLUE_DATA_USER_SOURCE_DATA_DIR env var.",
    type=click.Path(path_type=Path),
)
@click.option(
    "--schema-path",
    envvar="BLUE_DATA_USER_SOURCE_SCHEMA_PATH",
    default=None,
    help="Path to schema.json for KB schema seeding.",
    type=click.Path(exists=True, path_type=Path),
)
@click.pass_context
def cli(ctx: click.Context, database: str | None, data_dir: Path, schema_path: Path | None) -> None:
    """udb — user database CLI."""
    ctx.ensure_object(dict)
    ctx.obj["database"] = database
    ctx.obj["data_dir"] = data_dir
    ctx.obj["schema_path"] = schema_path


# ------------------------------------------------------------------ #
# udb database                                                        #
# ------------------------------------------------------------------ #

@cli.group("database")
def database_group() -> None:
    """User database management."""


@database_group.command("list")
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
)
@click.pass_obj
def database_list(obj: dict, fmt: str) -> None:
    """List all registered user databases."""
    source = _make_source(obj["data_dir"])
    names = source.list_users()
    sel_path = _selected_db_path(obj["data_dir"])
    selected = sel_path.read_text().strip() if sel_path.exists() else None
    if fmt == "json":
        rows = []
        for n in names:
            entry = source.get_user(n) or {}
            rows.append({"name": n, "selected": n == selected, **entry})
        console.print_json(json.dumps(rows))
        return
    if not names:
        console.print("[dim](no databases)[/dim]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("Name", style="bold")
    t.add_column("Registry", style="dim")
    t.add_column("", max_width=3)
    for name in names:
        entry = source.get_user(name) or {}
        reg = entry.get("registry", {})
        protocol = reg.get("connection", {}).get("protocol", "json/memory")
        marker = "[green]*[/green]" if name == selected else ""
        t.add_row(name, protocol, marker)
    console.print(t)


@database_group.command("create")
@click.argument("name")
@click.option(
    "--kb-backend",
    default="file",
    type=click.Choice(["memory", "file", "neo4j"]),
    show_default=True,
    help="KBSource backend to use.",
)
@click.option("--neo4j-host", default="localhost", show_default=True, help="Neo4j host (neo4j backend only).")
@click.option("--neo4j-port", default=7687, show_default=True, type=int, help="Neo4j bolt port.")
@click.option("--neo4j-user", default="neo4j", show_default=True, help="Neo4j username.")
@click.option("--neo4j-password", default=None, help="Neo4j password.")
@click.option(
    "--kb-search-mode",
    default="bm25",
    type=click.Choice(["none", "bm25", "semantic"]),
    show_default=True,
    help=(
        "Schema/data search index for the KB (used by extraction and entity/fact "
        "dedup, among others). 'none' falls back to a much weaker exact-substring "
        "schema lookup."
    ),
)
@click.option(
    "--kb-vector-backend",
    default="file",
    type=click.Choice(["memory", "file"]),
    show_default=True,
    help="Vector store backend for KB semantic search (--kb-search-mode=semantic only).",
)
@click.option(
    "--kb-embedding-model",
    default="text-embedding-3-small",
    show_default=True,
    help="OpenAI embedding model for KB semantic search (--kb-search-mode=semantic only).",
)
@click.option(
    "--doc-backend",
    default="file",
    type=click.Choice(["memory", "file"]),
    show_default=True,
    help="Vector backend for per-session interaction-transcript storage.",
)
@click.option(
    "--onboard/--no-onboard",
    default=True,
    show_default=True,
    help="Ask the new user a few onboarding questions to seed their data and metadata.",
)
@click.option(
    "--metadata-onboard/--no-metadata-onboard",
    default=True,
    show_default=True,
    help="Include structured metadata questions in onboarding (KB questions are always asked).",
)
@click.pass_obj
def database_create(
    obj: dict,
    name: str,
    kb_backend: str,
    neo4j_host: str,
    neo4j_port: int,
    neo4j_user: str,
    neo4j_password: str | None,
    kb_search_mode: str,
    kb_vector_backend: str,
    kb_embedding_model: str,
    doc_backend: str,
    onboard: bool,
    metadata_onboard: bool,
) -> None:
    """Create a new user database."""
    data_dir: Path = obj["data_dir"]
    schema_path: Path | None = obj.get("schema_path")
    source = _make_source(data_dir, schema_path)

    if name in source.list_users():
        err.print(f"[red]Error:[/red] Database '{name}' already exists.")
        sys.exit(1)

    kb_extras: dict[str, Any] = {}
    if kb_backend == "neo4j":
        if not neo4j_password:
            err.print("[red]Error:[/red] neo4j backend requires --neo4j-password.")
            sys.exit(1)
        kb_extras = {
            "host": neo4j_host,
            "port": neo4j_port,
            "user": neo4j_user,
            "password": neo4j_password,
        }

    try:
        asyncio.run(source.create_user(
            name,
            _user_registry_props(data_dir, name),
            _user_kb_props(
                data_dir, name, kb_backend,
                kb_search_mode=kb_search_mode,
                kb_vector_backend=kb_vector_backend,
                kb_embedding_model=kb_embedding_model,
                **kb_extras,
            ),
            _user_metadata_props(data_dir, name),
            _user_contact_props(data_dir, name),
            _user_session_props(data_dir, name),
            _user_doc_source_props(data_dir, name, doc_backend),
            onboard=onboard,
            onboard_metadata=metadata_onboard,
        ))
    except UDbError as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    _selected_db_path(data_dir).write_text(name)
    console.print(f"Created database: [bold]{name}[/bold] (selected)")


@database_group.command("onboard")
@click.option(
    "--metadata-onboard/--no-metadata-onboard",
    default=True,
    show_default=True,
    help="Include structured metadata questions in onboarding (KB questions are always asked).",
)
@click.pass_obj
def database_onboard(obj: dict, metadata_onboard: bool) -> None:
    """Ask the active database's user onboarding questions to seed data and metadata."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"], obj.get("schema_path"))
    try:
        asyncio.run(source.onboard_user(db, include_metadata=metadata_onboard))
    except UDbError as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"Onboarded database: [bold]{db}[/bold]")


@database_group.command("delete")
@click.argument("name")
@click.option("--yes", is_flag=True, default=False, help="Skip confirmation prompt.")
@click.pass_obj
def database_delete(obj: dict, name: str, yes: bool) -> None:
    """Delete a user database and all its data."""
    if not yes:
        click.confirm(f"Delete database '{name}' and all its data?", abort=True)
    source = _make_source(obj["data_dir"])
    try:
        asyncio.run(source.delete_user(name))
    except UDbError as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    sel_path = _selected_db_path(obj["data_dir"])
    if sel_path.exists() and sel_path.read_text().strip() == name:
        sel_path.unlink()
        sess_sel_path = _selected_session_path(obj["data_dir"])
        if sess_sel_path.exists():
            sess_sel_path.unlink()
    console.print(f"Deleted database: [bold]{name}[/bold]")


@database_group.command("select")
@click.argument("name")
@click.pass_obj
def database_select(obj: dict, name: str) -> None:
    """Select the active database."""
    data_dir: Path = obj["data_dir"]
    source = _make_source(data_dir)
    if name not in source.list_users():
        err.print(f"[red]Error:[/red] Database '{name}' not found.")
        sys.exit(1)
    _selected_db_path(data_dir).write_text(name)
    console.print(f"Selected database: [bold]{name}[/bold]")


@database_group.command("search")
@click.argument("keyword")
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
)
@click.pass_obj
def database_search(obj: dict, keyword: str, fmt: str) -> None:
    """Search databases by keyword."""
    source = _make_source(obj["data_dir"])
    kw = keyword.lower()
    matches = [n for n in source.list_users() if kw in n.lower()]
    if fmt == "json":
        console.print_json(json.dumps(matches))
        return
    if not matches:
        console.print("[dim](no matches)[/dim]")
        return
    for name in matches:
        console.print(name)


@database_group.command("reset")
@click.option("--yes", is_flag=True, default=False, help="Skip confirmation prompt.")
@click.pass_obj
def database_reset(obj: dict, yes: bool) -> None:
    """Reset the active database, clearing KB data and reseeding the schema."""
    db = _get_db(obj)
    if not yes:
        click.confirm(f"Reset database '{db}'? This will clear all KB data.", abort=True)
    source = _make_source(obj["data_dir"], obj.get("schema_path"))
    try:
        asyncio.run(source.reset_user(db))
    except UDbError as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"Reset database: [bold]{db}[/bold]")


@database_group.group("config")
def database_config_group() -> None:
    """Database configuration."""


@database_config_group.command("show")
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
)
@click.pass_obj
def database_config_show(obj: dict, fmt: str) -> None:
    """Show stored configuration for the active database."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    entry = source.get_user(db)
    if entry is None:
        err.print(f"[red]Error:[/red] Database '{db}' not found.")
        sys.exit(1)
    if fmt == "json":
        console.print_json(json.dumps(entry))
        return

    def _flatten(d: dict, prefix: str = "") -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for k, v in d.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                rows.extend(_flatten(v, full_key))
            else:
                rows.append((full_key, str(v)))
        return rows

    t = Table(show_header=True, header_style="bold")
    t.add_column("Key", style="bold")
    t.add_column("Value", style="dim")
    for key, value in _flatten(entry):
        t.add_row(key, value)
    console.print(t)


# ------------------------------------------------------------------ #
# udb session                                                         #
# ------------------------------------------------------------------ #

@cli.group("session")
def session_group() -> None:
    """Session management — a session groups the queries/interactions of one conversation."""


@session_group.command("start")
@click.pass_obj
def session_start(obj: dict) -> None:
    """Create a new session for the active database and select it."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    session_id = asyncio.run(source.create_session(db))
    _selected_session_path(obj["data_dir"]).write_text(session_id)
    console.print(f"Started session: [bold]{session_id}[/bold] (selected)")


@session_group.command("select")
@click.argument("session_id")
@click.pass_obj
def session_select(obj: dict, session_id: str) -> None:
    """Select the active session, so 'udb data query' doesn't need --session."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    if asyncio.run(source.get_session(db, session_id)) is None:
        err.print(f"[red]Error:[/red] Session '{session_id}' not found.")
        sys.exit(1)
    _selected_session_path(obj["data_dir"]).write_text(session_id)
    console.print(f"Selected session: [bold]{session_id}[/bold]")


@session_group.command("end")
@click.argument("session_id", required=False, default=None)
@click.pass_obj
def session_end(obj: dict, session_id: str | None) -> None:
    """End a session (defaults to the selected session). Clears the selection if it matches."""
    db = _get_db(obj)
    data_dir: Path = obj["data_dir"]
    sid = _get_session(obj, session_id)
    if sid is None:
        err.print("[red]Error:[/red] No session selected. Pass SESSION_ID or run 'udb session select ID'.")
        sys.exit(1)
    source = _make_source(data_dir)
    try:
        asyncio.run(source.end_session(db, sid))
    except UDbError as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    sel_path = _selected_session_path(data_dir)
    if sel_path.exists() and sel_path.read_text().strip() == sid:
        sel_path.unlink()
    console.print(f"Ended session: [bold]{sid}[/bold]")


@session_group.command("list")
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
)
@click.pass_obj
def session_list(obj: dict, fmt: str) -> None:
    """List sessions for the active database."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    sessions = asyncio.run(source.list_sessions(db))
    selected = _get_session(obj, None)
    if fmt == "json":
        console.print_json(json.dumps(sessions))
        return
    if not sessions:
        console.print("[dim](no sessions)[/dim]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("Session ID", style="bold")
    t.add_column("Status")
    t.add_column("Queries", justify="right")
    t.add_column("Created")
    t.add_column("", max_width=3)
    for sid, record in sessions.items():
        marker = "[green]*[/green]" if sid == selected else ""
        t.add_row(sid, record.get("status", ""), str(len(record.get("queries", {}))),
                   _humanize_date(record.get("created_at")), marker)
    console.print(t)


@session_group.command("show")
@click.argument("session_id", required=False, default=None)
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
)
@click.pass_obj
def session_show(obj: dict, session_id: str | None, fmt: str) -> None:
    """Show a session's queries and interactions (defaults to the selected session)."""
    db = _get_db(obj)
    sid = _get_session(obj, session_id)
    if sid is None:
        err.print("[red]Error:[/red] No session selected. Pass SESSION_ID or run 'udb session select ID'.")
        sys.exit(1)
    source = _make_source(obj["data_dir"])
    record = asyncio.run(source.get_session(db, sid))
    if record is None:
        err.print(f"[red]Error:[/red] Session '{sid}' not found.")
        sys.exit(1)
    if fmt == "json":
        console.print_json(json.dumps(record))
        return
    console.print(f"Session [bold]{sid}[/bold] — status: {record.get('status')}, created: {_humanize_date(record.get('created_at'))}")
    for qid, q in record.get("queries", {}).items():
        console.print(f"\n[bold]Query[/bold] {qid}: {q.get('query')}")
        for iid, ia in q.get("interactions", {}).items():
            console.print(f"  [dim]interaction {iid}[/dim] ({ia.get('status')}) via {ia.get('contact', {}).get('protocol')}")
            console.print(f"    Q: {ia.get('question')}")
            console.print(f"    A: {ia.get('response')}")


# ------------------------------------------------------------------ #
# udb data                                                            #
# ------------------------------------------------------------------ #

@cli.group("data")
def data_group() -> None:
    """Instance data management."""


@data_group.command("list")
@click.option("--show-provenance", "show_provenance", is_flag=True, help="Include provenance text.")
@click.option("--show-detailed", "show_detailed", is_flag=True,
              help="Include each row's node attributes: description, created, modified.")
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
)
@click.pass_obj
def data_list(obj: dict, show_provenance: bool, show_detailed: bool, fmt: str) -> None:
    """List all entities, property values, and facts in the database."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        manager = source._get_manager(db)
        kb = manager._ensure_kb_source()
        rows: list[dict] = asyncio.run(
            kb.fetch_database_data(db, include_provenance=show_provenance, compact=True, detailed=show_detailed)
        )
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if fmt == "json":
        console.print_json(json.dumps(rows))
        return

    entities   = [r for r in rows if r.get("relation_type") == "IS_INSTANCE_OF"]
    all_props  = [r for r in rows if r.get("relation_type") == "IS_VALUE_OF"]
    ent_props  = [r for r in all_props if r.get("owner_label") != "FACT"]
    fact_props = [r for r in all_props if r.get("owner_label") == "FACT"]
    facts      = [r for r in rows if r.get("relation_type") == "REPRESENTS"]

    def _detail_columns(t: Table) -> None:
        t.add_column("Description", style="dim")
        t.add_column("Created",     style="dim")
        t.add_column("Modified",    style="dim")

    def _detail_row(r: dict) -> list[str]:
        return [r.get("description") or "", _humanize_date(r.get("created")), _humanize_date(r.get("modified"))]

    def _provenance_columns(t: Table) -> None:
        t.add_column("Provenance", style="dim")
        t.add_column("Source",     style="dim")

    def _provenance_row(r: dict) -> list[str]:
        return [r.get("extraction", "") or "", r.get("source", "") or ""]

    def _source_original_column(t: Table) -> None:
        t.add_column("Source Original", style="dim")

    def _source_original_row(r: dict) -> list[str]:
        return [r.get("source_original") or ""]

    if entities:
        t = Table(title="Entities", show_header=True, header_style="bold")
        t.add_column("Name",  style="bold")
        t.add_column("Class", style="dim")
        if show_detailed:
            _detail_columns(t)
        if show_provenance:
            _provenance_columns(t)
        if show_detailed and show_provenance:
            _source_original_column(t)
        for r in sorted(entities, key=lambda x: (x.get("class_name") or "", x.get("entity_name") or "")):
            row = [r.get("entity_name") or "", r.get("class_name") or ""]
            if show_detailed:
                row += _detail_row(r)
            if show_provenance:
                row += _provenance_row(r)
            if show_detailed and show_provenance:
                row += _source_original_row(r)
            t.add_row(*row)
        console.print(t)

    if ent_props:
        t = Table(title="Entity Property Values", show_header=True, header_style="bold")
        t.add_column("Entity",   style="bold")
        t.add_column("Property", style="dim")
        t.add_column("Value")
        if show_detailed:
            _detail_columns(t)
        if show_provenance:
            _provenance_columns(t)
        if show_detailed and show_provenance:
            _source_original_column(t)
        for r in sorted(ent_props, key=lambda x: (x.get("entity_name") or "", x.get("property_name") or "")):
            row = [r.get("entity_name") or "", r.get("property_name") or "", str(r.get("property_value", ""))]
            if show_detailed:
                row += _detail_row(r)
            if show_provenance:
                row += _provenance_row(r)
            if show_detailed and show_provenance:
                row += _source_original_row(r)
            t.add_row(*row)
        console.print(t)

    if facts:
        t = Table(title="Facts", show_header=True, header_style="bold")
        t.add_column("Head",     style="bold")
        t.add_column("Relation", style="dim")
        t.add_column("Tail",     style="bold")
        if show_detailed:
            _detail_columns(t)
        if show_provenance:
            _provenance_columns(t)
        if show_detailed and show_provenance:
            _source_original_column(t)
        for r in sorted(facts, key=lambda x: (x.get("relation_name") or "", x.get("source_name") or "")):
            row = [r.get("source_name") or "", r.get("relation_name") or "", r.get("target_name") or ""]
            if show_detailed:
                row += _detail_row(r)
            if show_provenance:
                row += _provenance_row(r)
            if show_detailed and show_provenance:
                row += _source_original_row(r)
            t.add_row(*row)
        console.print(t)

    if fact_props:
        t = Table(title="Fact Property Values", show_header=True, header_style="bold")
        t.add_column("Head",     style="bold")
        t.add_column("Relation", style="dim")
        t.add_column("Tail",     style="bold")
        t.add_column("Property", style="dim")
        t.add_column("Value")
        if show_detailed:
            _detail_columns(t)
        if show_provenance:
            _provenance_columns(t)
        if show_detailed and show_provenance:
            _source_original_column(t)
        for r in sorted(fact_props, key=lambda x: (x.get("relation_name") or "", x.get("head_name") or "", x.get("property_name") or "")):
            row = [
                r.get("head_name") or "",
                r.get("relation_name") or "",
                r.get("tail_name") or "",
                r.get("property_name") or "",
                str(r.get("property_value", "")),
            ]
            if show_detailed:
                row += _detail_row(r)
            if show_provenance:
                row += _provenance_row(r)
            if show_detailed and show_provenance:
                row += _source_original_row(r)
            t.add_row(*row)
        console.print(t)

    if not entities and not all_props and not facts:
        console.print("[dim](no instances)[/dim]")


@data_group.command("query")
@click.argument("text")
@click.option("--session", default=None, help="Session ID for query context.")
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json", "nl"]),
    default="table",
    show_default=True,
)
@click.option("--top-k", "top_k", default=10, type=int, show_default=True)
@click.option(
    "--include-expanded", "include_expanded", is_flag=True, default=False,
    help="Also return the per-sub-question queries and their raw results.",
)
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show tool call arguments in the status line.")
@click.option("--log", "-l", is_flag=True, default=False, help="Log each tool call and result on its own line.")
@click.option("--log-limit", "log_limit", default=80, type=int, show_default=True, help="Truncation limit for logged values.")
@click.pass_obj
def data_query(
    obj: dict, text: str, session: str | None, fmt: str, top_k: int, include_expanded: bool,
    verbose: bool, log: bool, log_limit: int,
) -> None:
    """Execute a natural-language query against the database."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    props: dict[str, Any] = {"top_k": top_k}
    resolved_session = _get_session(obj, session)
    if resolved_session:
        props["session"] = resolved_session
    if fmt == "nl":
        props["output_form"] = "nl"
    if include_expanded:
        props["include_expanded"] = True
    try:
        with console.status("Querying…") as status:
            on_tool_call, on_tool_result = _status_tool_callbacks(
                status, "Querying", verbose=verbose, log=log, log_limit=log_limit
            )
            props["on_tool_call"] = on_tool_call
            props["on_tool_result"] = on_tool_result
            results, session_id = source.execute_query(text, database=db, optional_properties=props)
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if not resolved_session:
        # Auto-select-after-auto-create: continue this session on the next query
        # without requiring an explicit 'udb session select'.
        _selected_session_path(obj["data_dir"]).write_text(session_id)
    answer = results["result"] if isinstance(results, dict) else results
    expanded = results.get("expanded") if isinstance(results, dict) else None

    if fmt == "nl":
        click.echo(answer)
        if expanded is not None:
            console.print("\n[bold]Expanded:[/bold]")
            console.print(expanded)
        return
    if fmt == "json":
        click.echo(json.dumps(results, indent=2, default=str))
        return
    rows: list[dict] = answer  # type: ignore[assignment]
    if not rows:
        console.print("[dim](no results)[/dim]")
    else:
        columns = sorted({k for row in rows for k in row})
        t = Table(show_header=True, header_style="bold")
        for col in columns:
            t.add_column(col)
        for row in rows:
            t.add_row(*[str(row.get(col, "")) for col in columns])
        console.print(t)
    if expanded is not None:
        console.print("\n[bold]Expanded:[/bold]")
        et = Table(show_header=True, header_style="bold")
        et.add_column("Query", style="cyan")
        et.add_column("Results")
        for e in expanded:
            et.add_row(e["query"], ", ".join(str(x) for x in e["results"]))
        console.print(et)


@data_group.command("search")
@click.argument("query")
@click.option(
    "--type", "types",
    type=click.Choice(["entity", "fact"], case_sensitive=False),
    multiple=True,
    help="Restrict to a node type (repeatable). Default: all types.",
)
@click.option(
    "--mode",
    type=click.Choice(["keyword", "semantic"]),
    default="keyword",
    show_default=True,
)
@click.option("--top-k", "top_k", default=10, show_default=True, type=int)
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
)
@click.pass_obj
def data_search(obj: dict, query: str, types: tuple[str, ...], mode: str, top_k: int, fmt: str) -> None:
    """Search entities and facts by keyword or semantic similarity."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    type_filter = [t.upper() for t in types] if types else None
    try:
        manager = source._get_manager(db)
        kb = manager._ensure_kb_source()
        results = asyncio.run(kb.search_data(db, query, k=top_k, mode=mode, type_filter=type_filter))
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if fmt == "json":
        console.print_json(json.dumps([
            {
                "id": r.id, "type": r.type, "name": r.name, "description": r.description,
                "class_name": r.class_name,
                "head_name": r.head_name, "relation_name": r.relation_name, "tail_name": r.tail_name,
            }
            for r in results
        ]))
        return
    if not results:
        console.print("[dim](no results)[/dim]")
        return
    entities = [r for r in results if r.type == "ENTITY"]
    facts = [r for r in results if r.type == "FACT"]
    if entities:
        t = Table(title="Entities", show_header=True, header_style="bold")
        t.add_column("Name", style="bold")
        t.add_column("Class", style="dim")
        t.add_column("Description")
        for r in entities:
            t.add_row(r.name, r.class_name or "", r.description or "")
        console.print(t)
    if facts:
        t = Table(title="Facts", show_header=True, header_style="bold")
        t.add_column("Head", style="bold")
        t.add_column("Relation", style="dim")
        t.add_column("Tail", style="bold")
        t.add_column("Description")
        for r in facts:
            t.add_row(r.head_name or "", r.relation_name or "", r.tail_name or "", r.description or "")
        console.print(t)


@data_group.command("import")
@click.argument("input_file", type=click.File("r"))
@click.pass_obj
def data_import(obj: dict, input_file) -> None:
    """Import instance data previously produced by `udb data export` (KG only).

    Schema must already exist — import it first with `udb schema import`.
    """
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        data_json = json.load(input_file)
    except json.JSONDecodeError as exc:
        err.print(f"[red]Error:[/red] Invalid JSON in {input_file.name}: {exc}")
        sys.exit(1)
    try:
        manager = source._get_manager(db)
        kb = manager._ensure_kb_source()
        asyncio.run(kb.import_database_data(db, data_json))
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"Imported data into database: [bold]{db}[/bold]")


@data_group.command("export")
@click.option("--show-provenance", "show_provenance", is_flag=True, help="Include provenance text.")
@click.option("--output", "-o", type=click.File("w"), default="-", show_default=True,
              help="Write JSON to this file (default: stdout).")
@click.pass_obj
def data_export(obj: dict, show_provenance: bool, output) -> None:
    """Export the database's instance data (entities, facts, property values) as JSON.

    Does not include schema — use `udb schema export` for that, and import it
    first so `udb data import` has classes/relations/properties to resolve against.
    """
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        manager = source._get_manager(db)
        kb = manager._ensure_kb_source()
        data_json = asyncio.run(kb.export_database_data(db, include_provenance=show_provenance))
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    json.dump(data_json, output, indent=2)
    output.write("\n")


@data_group.command("extract")
@click.argument("text")
@click.option("--query", "queries", multiple=True, help="Guiding question (repeatable).")
@click.option("--source", "source_name", default=None, help="Source name for provenance.")
@click.option("--model", default="gpt-4o", show_default=True, help="OpenAI model.")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show tool call arguments in the status line.")
@click.option("--log", "-l", is_flag=True, default=False, help="Log each tool call and result on its own line.")
@click.option("--log-limit", "log_limit", default=80, type=int, show_default=True, help="Truncation limit for logged values.")
@click.pass_obj
def data_extract(
    obj: dict,
    text: str,
    queries: tuple[str, ...],
    source_name: str | None,
    model: str,
    verbose: bool,
    log: bool,
    log_limit: int,
) -> None:
    """Extract entities, facts, and property values from free text.

    Requires the openai extra: pip install 'blue-data-kb-source[openai]'
    and OPENAI_API_KEY in the environment.
    """
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        manager = source._get_manager(db)
        kb = manager._ensure_kb_source()
        source_id: str | None = None
        if source_name:
            nodes = kb.match_nodes(db, label="SOURCE")
            for n in nodes:
                if n.get("properties", {}).get("name") == source_name:
                    source_id = n["id"]
                    break
            if source_id is None:
                err.print(f"[red]Error:[/red] Source '{source_name}' not found.")
                sys.exit(1)
        with console.status("Extracting…") as status:
            on_tool_call, on_tool_result = _status_tool_callbacks(
                status, "Extracting", verbose=verbose, log=log, log_limit=log_limit
            )
            asyncio.run(kb.import_text(
                db, text,
                queries=list(queries) or None,
                model=model,
                source_id=source_id,
                on_tool_call=on_tool_call,
                on_tool_result=on_tool_result,
            ))
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print("Extraction complete.")


# ------------------------------------------------------------------ #
# udb data source                                                     #
# ------------------------------------------------------------------ #

@data_group.group("source")
def source_group() -> None:
    """Data source management."""


@source_group.command("list")
@click.option("--show-detailed", "show_detailed", is_flag=True,
              help="Include created/modified timestamps in the table output.")
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
)
@click.pass_obj
def source_list(obj: dict, show_detailed: bool, fmt: str) -> None:
    """List data sources.

    Shows user-added sources only (excludes internal kb/metadata/contacts sources).
    Sources present in the KG but removed from the registry are marked (*).
    """
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        manager = source._get_manager(db)
        reg_records = [
            r for r in (manager._registry.list_records(record_type="source", scope="/") or [])
            if r.get("name") not in _INTERNAL_SOURCES
        ]
        kg_sources = asyncio.run(manager.list_sources())
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    # Build lookup maps from KG source nodes
    ks_by_id:   dict[str, dict] = {ks.get("id", ""): ks for ks in kg_sources}
    ks_by_name: dict[str, dict] = {ks.get("name", ks.get("id", "")): ks for ks in kg_sources}
    reg_names:  set[str]        = {r.get("name") for r in reg_records}

    rows: list[dict] = []
    for r in reg_records:
        props    = r.get("properties") or {}
        sid      = props.get("source_id", "")
        ks       = ks_by_id.get(sid) or ks_by_name.get(r.get("name", "")) or {}
        rows.append({
            "name":        r.get("name", ""),
            "location":    props.get("connection", {}).get("path", ""),
            "description": r.get("description", ""),
            "original":    ks.get("original", ""),
            "created":     ks.get("created", ""),
            "modified":    ks.get("modified", ""),
            "in_registry": True,
        })
    for ks in kg_sources:
        name = ks.get("name", ks.get("id", ""))
        if name not in reg_names:
            rows.append({
                "name":        name,
                "location":    ks.get("source", ks.get("location", "")),
                "description": ks.get("description", ""),
                "original":    ks.get("original", ""),
                "created":     ks.get("created", ""),
                "modified":    ks.get("modified", ""),
                "in_registry": False,
            })

    if fmt == "json":
        console.print_json(json.dumps(rows))
        return
    if not rows:
        console.print("[dim](no sources)[/dim]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("Name",        style="bold")
    t.add_column("Location",    style="dim")
    t.add_column("Description", style="dim")
    t.add_column("Original",    style="dim")
    if show_detailed:
        t.add_column("Created",  style="dim")
        t.add_column("Modified", style="dim")
    t.add_column("", max_width=5)
    for row in rows:
        marker = "[dim](*)[/dim]" if not row["in_registry"] else ""
        cells  = [row["name"], row["location"], row["description"], row["original"]]
        if show_detailed:
            cells += [_humanize_date(row["created"]), _humanize_date(row["modified"])]
        cells.append(marker)
        t.add_row(*cells)
    console.print(t)


@source_group.command("add")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--query", "queries",
    multiple=True,
    help="Query to additionally extract facts for into the KB (Type 2 import). May be repeated.",
)
@click.option("--name", default=None, help="Human-readable label (defaults to source value).")
@click.option("--description", default=None, help="Optional description.")
@click.option("--original", default=None, help="Original date of the source (e.g. when it was published).")
@click.option(
    "--effort",
    default="medium",
    type=click.Choice(["low", "medium", "high"]),
    show_default=True,
    help="Extraction passes over the document (low/medium/high = 1/2/3). More passes "
         "catch more of a dense document, at proportionally more LLM calls.",
)
@click.pass_obj
def source_add(obj: dict, file: Path, queries: tuple[str, ...], name: str | None, description: str | None, original: str | None, effort: str) -> None:
    """Register a file (.txt/.pdf/.docx) as a data source.

    The file is always parsed, chunked, and embedded into the shared
    "external_documents" DocumentDataSource, making it searchable. Pass
    --query to additionally extract facts from it into the KB.
    """
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    props: dict[str, Any] = {}
    if queries:
        props["queries"] = list(queries)
    if name:
        props["name"] = name
    if description:
        props["description"] = description
    if original:
        props["original"] = original
    props["effort"] = effort
    try:
        asyncio.run(source.add_source(file, database=db, optional_properties=props or None))
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    label = sanitize_registry_name(name or str(file))
    if queries:
        n = len(queries)
        console.print(f"Ingested source: [bold]{label}[/bold] ({n} {'query' if n == 1 else 'queries'} extracted to KB)")
    else:
        console.print(f"Ingested source: [bold]{label}[/bold]")


@source_group.command("remove")
@click.argument("name")
@click.option("--yes", is_flag=True, default=False, help="Skip confirmation prompt.")
@click.pass_obj
def source_remove(obj: dict, name: str, yes: bool) -> None:
    """Remove a source from the registry (KG data is preserved)."""
    db = _get_db(obj)
    if not yes:
        click.confirm(
            f"Remove source '{name}' from registry? KG data will be preserved.", abort=True
        )
    source = _make_source(obj["data_dir"])
    try:
        source.remove_source(db, name)
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"Removed source from registry: [bold]{name}[/bold]")


# ------------------------------------------------------------------ #
# udb schema                                                          #
# ------------------------------------------------------------------ #

@cli.group("schema")
def schema_group() -> None:
    """Schema management."""


@schema_group.command("list")
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
)
@click.pass_obj
def schema_list(obj: dict, fmt: str) -> None:
    """List classes, relations, and their properties."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        manager = source._get_manager(db)
        kb = manager._ensure_kb_source()
        schema = asyncio.run(kb.fetch_database_schema(db))
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if fmt == "json":
        console.print_json(json.dumps(schema.to_json()))
        return
    if not schema.entities and not schema.relations:
        console.print("[dim](no schema declared)[/dim]")
        return

    class_names = set(schema.entities.keys())
    subclass_rels = [r for r in schema.relations.values() if r["name"] == "IS_SUBCLASS_OF"]
    real_relations = {k: v for k, v in schema.relations.items() if v["name"] != "IS_SUBCLASS_OF"}
    class_hierarchy    = [(r["source"], r["target"]) for r in subclass_rels if r["source"] in class_names]
    relation_hierarchy = [(r["source"], r["target"]) for r in subclass_rels if r["source"] not in class_names]

    if schema.entities:
        t = Table(title="Classes", show_header=True, header_style="bold")
        t.add_column("Name", style="bold", min_width=12)
        t.add_column("Description")
        for entity in sorted(schema.entities.values(), key=lambda e: e["name"]):
            t.add_row(entity["name"], entity.get("description", ""))
        console.print(t)

    class_props = [
        (entity["name"], attr_name, attr.get("description", ""))
        for entity in schema.entities.values()
        for attr_name, attr in entity.get("contents", {}).get("attributes", {}).items()
    ]
    if class_props:
        t = Table(title="Class Properties", show_header=True, header_style="bold")
        t.add_column("Class", style="bold", min_width=12)
        t.add_column("Property", style="bold", min_width=12)
        t.add_column("Description")
        for row in sorted(class_props):
            t.add_row(*row)
        console.print(t)

    if class_hierarchy:
        t = Table(title="Class Hierarchy", show_header=True, header_style="bold")
        t.add_column("Child", style="bold", min_width=12)
        t.add_column("Parent", style="dim", min_width=12)
        for child, parent in sorted(class_hierarchy):
            t.add_row(child, parent)
        console.print(t)

    if real_relations:
        t = Table(title="Relations", show_header=True, header_style="bold")
        t.add_column("Source", style="dim", min_width=10)
        t.add_column("Relation", style="bold", min_width=12)
        t.add_column("Target", style="dim", min_width=10)
        t.add_column("Description")
        for rel in sorted(real_relations.values(), key=lambda r: r["name"]):
            t.add_row(rel.get("source", ""), rel["name"], rel.get("target", ""), rel.get("description", ""))
        console.print(t)

    rel_props = [
        (rel["name"], attr_name, attr.get("description", ""))
        for rel in real_relations.values()
        for attr_name, attr in rel.get("contents", {}).get("attributes", {}).items()
    ]
    if rel_props:
        t = Table(title="Relation Properties", show_header=True, header_style="bold")
        t.add_column("Relation", style="bold", min_width=12)
        t.add_column("Property", style="bold", min_width=12)
        t.add_column("Description")
        for row in sorted(rel_props):
            t.add_row(*row)
        console.print(t)

    if relation_hierarchy:
        t = Table(title="Relation Hierarchy", show_header=True, header_style="bold")
        t.add_column("Child", style="bold", min_width=12)
        t.add_column("Parent", style="dim", min_width=12)
        for child, parent in sorted(relation_hierarchy):
            t.add_row(child, parent)
        console.print(t)


@schema_group.command("import")
@click.argument("input_file", type=click.File("r"))
@click.pass_obj
def schema_import(obj: dict, input_file) -> None:
    """Import a schema previously produced by `udb schema export` (declares idempotently)."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        schema_json = json.load(input_file)
    except json.JSONDecodeError as exc:
        err.print(f"[red]Error:[/red] Invalid JSON in {input_file.name}: {exc}")
        sys.exit(1)
    try:
        manager = source._get_manager(db)
        kb = manager._ensure_kb_source()
        asyncio.run(kb.import_database_schema(db, schema_json))
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"Imported schema into database: [bold]{db}[/bold]")


@schema_group.command("export")
@click.option("--output", "-o", type=click.File("w"), default="-", show_default=True,
              help="Write JSON to this file (default: stdout).")
@click.pass_obj
def schema_export(obj: dict, output) -> None:
    """Export the database's schema as JSON, in the shape `udb schema import` reads back."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        manager = source._get_manager(db)
        kb = manager._ensure_kb_source()
        schema_json = asyncio.run(kb.export_database_schema(db))
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    json.dump(schema_json, output, indent=2)
    output.write("\n")


@schema_group.command("search")
@click.argument("query")
@click.option(
    "--type", "types",
    type=click.Choice(["CLASS", "RELATION", "PROPERTY"], case_sensitive=False),
    multiple=True,
    help="Filter by schema type (repeatable).",
)
@click.option(
    "--mode",
    type=click.Choice(["keyword", "semantic"]),
    default="keyword",
    show_default=True,
)
@click.option("--top-k", "top_k", default=10, show_default=True, type=int)
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
)
@click.pass_obj
def schema_search(obj: dict, query: str, types: tuple[str, ...], mode: str, top_k: int, fmt: str) -> None:
    """Search schema elements by keyword or semantic similarity."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    type_filter = [t.upper() for t in types] if types else None
    try:
        manager = source._get_manager(db)
        kb = manager._ensure_kb_source()
        results = asyncio.run(kb.search_schema(db, query, k=top_k, mode=mode, type_filter=type_filter))
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if fmt == "json":
        console.print_json(json.dumps([
            {"id": r.id, "type": r.type, "name": r.name, "description": r.description}
            for r in results
        ]))
        return
    if not results:
        console.print("[dim](no results)[/dim]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("Type", style="dim")
    t.add_column("Name", style="bold")
    t.add_column("Description")
    for r in results:
        t.add_row(r.type, r.name, r.description or "")
    console.print(t)


# ------------------------------------------------------------------ #
# udb metadata                                                        #
# ------------------------------------------------------------------ #

_METADATA_SCHEMA_PATH = Path(__file__).parent.parent.parent.parent.parent.parent / \
    "lib" / "src" / "blue_data_user_source" / "data" / "metadata_schema.json"

def _load_metadata_schema() -> dict:
    try:
        import importlib.resources as _ir
        with _ir.files("blue_data_user_source.data").joinpath("metadata_schema.json").open() as f:
            return json.load(f)
    except Exception:
        return {}

_METADATA_SCHEMA: dict = _load_metadata_schema()


def _parse_metadata_value(raw: str) -> Any:
    """Try JSON first so lists/booleans/numbers work; fall back to plain string."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw


def _print_metadata_node(key: str, value: Any, indent: int = 0) -> None:
    pad = "  " * indent
    if isinstance(value, dict):
        console.print(f"{pad}[bold]{key}[/bold]")
        for k, v in value.items():
            _print_metadata_node(k, v, indent + 1)
    elif isinstance(value, list):
        console.print(f"{pad}[bold]{key}[/bold]  [dim]{json.dumps(value)}[/dim]")
    else:
        console.print(f"{pad}[bold]{key}[/bold]  {value}")


@cli.group("metadata")
def metadata_group() -> None:
    """User metadata for agents acting on your behalf."""


@metadata_group.command("list")
@click.argument("path", nargs=-1)
@click.option("-r", "--recursive", is_flag=True, help="List all keys recursively as a flat key=value table.")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table", show_default=True)
@click.pass_obj
def metadata_list(obj: dict, path: tuple[str, ...], recursive: bool, fmt: str) -> None:
    """List metadata at the given path, or top-level categories if no path given.

    Examples:

    \b
      udb metadata list
      udb metadata list identity
      udb metadata list identity --recursive
      udb metadata list --recursive
    """
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        all_meta: dict[str, Any] = source.list_metadata(db)
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    node: Any = all_meta
    dotted = ".".join(path)
    for i, segment in enumerate(path):
        if not isinstance(node, dict) or segment not in node:
            if i == 0 and segment in _METADATA_SCHEMA:
                node = {}
                break
            err.print(f"[red]Error:[/red] Key not found: {dotted!r}")
            sys.exit(1)
        node = node[segment]

    if fmt == "json":
        console.print_json(json.dumps(node))
        return

    if recursive:
        def _merge_category(stored_cat: Any, schema_cat: dict) -> dict[str, Any]:
            """Merge stored values with schema field specs; schema keys always present."""
            stored_cat = stored_cat if isinstance(stored_cat, dict) else {}
            merged: dict[str, Any] = {}
            for field, spec in schema_cat.items():
                merged[field] = stored_cat.get(field)
            for k, v in stored_cat.items():
                if k not in merged:
                    merged[k] = v
            return merged

        def _flatten(subtree: Any, prefix: str = "") -> list[tuple[str, Any]]:
            if isinstance(subtree, dict):
                rows: list[tuple[str, Any]] = []
                for k, v in subtree.items():
                    full = f"{prefix}.{k}" if prefix else k
                    rows.extend(_flatten(v, full))
                return rows
            return [(prefix, subtree)]

        if not path:
            all_cats = dict.fromkeys(list(_METADATA_SCHEMA.keys()) + list(all_meta.keys()))
            merged_root: dict[str, Any] = {}
            for cat in all_cats:
                schema_cat = {k: v for k, v in _METADATA_SCHEMA.get(cat, {}).items() if not k.startswith("__")}
                merged_root[cat] = _merge_category(all_meta.get(cat), schema_cat)
            flat = _flatten(merged_root)
        else:
            schema_cat = {k: v for k, v in _METADATA_SCHEMA.get(path[0], {}).items() if not k.startswith("__")} if len(path) == 1 else {}
            merged_cat = _merge_category(node, schema_cat)
            flat = _flatten(merged_cat, dotted)

        t = Table(show_header=True, header_style="bold")
        t.add_column("Key", style="bold")
        t.add_column("Value")
        for key, val in flat:
            val_str = json.dumps(val) if isinstance(val, (list, dict)) else (str(val) if val is not None else "[dim]—[/dim]")
            t.add_row(key, val_str)
        if not flat:
            console.print("[dim](no metadata)[/dim]")
        else:
            console.print(t)
        return

    if not path:
        categories = dict.fromkeys(list(_METADATA_SCHEMA.keys()) + list(all_meta.keys()))
        t = Table(show_header=True, header_style="bold")
        t.add_column("Category", style="bold")
        t.add_column("Keys set", style="dim", justify="right")
        t.add_column("Description", style="dim")
        for cat in categories:
            stored = all_meta.get(cat)
            schema_cat = _METADATA_SCHEMA.get(cat, {})
            desc = schema_cat.get("__description__", "")
            count = sum(1 for k, v in (stored or {}).items() if v is not None) if isinstance(stored, dict) else (1 if stored is not None else 0)
            t.add_row(cat, str(count) if count else "[dim]—[/dim]", desc)
        console.print(t)
        return

    if isinstance(node, dict):
        schema_cat = _METADATA_SCHEMA.get(path[0], {}) if len(path) == 1 else {}
        schema_keys = {k: v for k, v in schema_cat.items() if not k.startswith("__")}
        all_keys = dict.fromkeys(list(schema_keys.keys()) + list(node.keys()))
        t = Table(show_header=True, header_style="bold")
        t.add_column("Key", style="bold")
        t.add_column("Value")
        t.add_column("Description", style="dim")
        for k in all_keys:
            v = node.get(k)
            val_str = json.dumps(v) if isinstance(v, (list, dict)) else (str(v) if v is not None else "[dim]—[/dim]")
            hint = schema_keys.get(k, {}).get("description", "") if isinstance(schema_keys.get(k), dict) else ""
            t.add_row(k, val_str, hint)
        console.print(t)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            console.print(f"[dim]{i}[/dim]  {item}")
    else:
        console.print(node)


@metadata_group.command("get")
@click.argument("path", nargs=-1, required=True)
@click.pass_obj
def metadata_get(obj: dict, path: tuple[str, ...]) -> None:
    """Get a metadata value.

    Examples:

    \b
      udb metadata get identity name
      udb metadata get privacy consent_level
    """
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    key = ".".join(path)
    try:
        value = source.get_metadata(db, key)
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if value is None:
        err.print(f"[yellow]Not set:[/yellow] {key}")
        sys.exit(1)
    if isinstance(value, (dict, list)):
        console.print_json(json.dumps(value))
    else:
        console.print(value)


@metadata_group.command("set")
@click.argument("args", nargs=-1, required=True)
@click.pass_obj
def metadata_set(obj: dict, args: tuple[str, ...]) -> None:
    """Set a metadata value. Path segments precede the value.

    Examples:

    \b
      udb metadata set identity name "Alice"
      udb metadata set preferences verbosity brief
      udb metadata set availability preferred_channel email
    """
    if len(args) < 2:
        err.print("[red]Error:[/red] Provide at least one key segment and a value.")
        sys.exit(1)
    *key_parts, raw_value = args
    key = ".".join(key_parts)
    value = _parse_metadata_value(raw_value)
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        source.set_metadata(db, key, value)
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    display = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
    console.print(f"[green]Set[/green] {key} = {display}")


@metadata_group.command("delete")
@click.argument("path", nargs=-1, required=True)
@click.option("--yes", is_flag=True, default=False, help="Skip confirmation prompt.")
@click.pass_obj
def metadata_delete(obj: dict, path: tuple[str, ...], yes: bool) -> None:
    """Delete a metadata key.

    Examples:

    \b
      udb metadata delete identity pronouns
    """
    key = ".".join(path)
    if not yes:
        click.confirm(f"Delete metadata key {key!r}?", abort=True)
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        source.delete_metadata(db, key)
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"[green]Deleted[/green] {key}")


# ------------------------------------------------------------------ #
# udb contact                                                         #
# ------------------------------------------------------------------ #

def _load_contact_schema() -> dict:
    try:
        import importlib.resources as _ir
        with _ir.files("blue_data_user_source.data").joinpath("contact_schema.json").open() as f:
            return json.load(f)
    except Exception:
        return {}

_CONTACT_SCHEMA: dict = _load_contact_schema()


@cli.group("contact")
def contact_group() -> None:
    """Contact methods for agents to reach you."""


@contact_group.command("list")
@click.argument("path", nargs=-1)
@click.option("-r", "--recursive", is_flag=True, help="List all fields recursively as a flat key=value table.")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table", show_default=True)
@click.pass_obj
def contact_list(obj: dict, path: tuple[str, ...], recursive: bool, fmt: str) -> None:
    """List contacts at the given path, or all protocols if no path given.

    Examples:

    \b
      udb contact list
      udb contact list email
      udb contact list email work
      udb contact list email --recursive
      udb contact list --recursive
    """
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        all_contacts: dict = source._get_manager(db).get_contacts()
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    dotted = ".".join(path)
    node: Any = all_contacts
    for i, segment in enumerate(path):
        if not isinstance(node, dict) or segment not in node:
            # Known schema protocol with no entries yet
            if i == 0 and segment in _CONTACT_SCHEMA:
                node = {}
                break
            err.print(f"[red]Error:[/red] Key not found: {dotted!r}")
            sys.exit(1)
        node = node[segment]

    if fmt == "json":
        console.print_json(json.dumps(node))
        return

    if recursive:
        def _merge_entry(stored_entry: Any, schema_fields: dict) -> dict[str, Any]:
            """Merge stored values with schema field specs; schema keys always present."""
            stored_entry = stored_entry if isinstance(stored_entry, dict) else {}
            merged: dict[str, Any] = {}
            for field in schema_fields:
                merged[field] = stored_entry.get(field)
            for k, v in stored_entry.items():
                if k not in merged:
                    merged[k] = v
            return merged

        def _flatten(subtree: Any, prefix: str = "") -> list[tuple[str, Any]]:
            if isinstance(subtree, dict):
                rows: list[tuple[str, Any]] = []
                for k, v in subtree.items():
                    full = f"{prefix}.{k}" if prefix else k
                    rows.extend(_flatten(v, full))
                return rows
            return [(prefix, subtree)]

        if not path:
            protocols = dict.fromkeys(list(_CONTACT_SCHEMA.keys()) + list(all_contacts.keys()))
            merged_root: dict[str, Any] = {}
            for proto in protocols:
                schema_fields = {k: v for k, v in _CONTACT_SCHEMA.get(proto, {}).items() if not k.startswith("__")}
                entries = all_contacts.get(proto, {})
                entries = entries if isinstance(entries, dict) else {}
                merged_proto = {
                    entry_name: _merge_entry(details, schema_fields)
                    for entry_name, details in entries.items()
                    if isinstance(details, dict)
                }
                if merged_proto:
                    merged_root[proto] = merged_proto
            flat = _flatten(merged_root)
        elif len(path) == 1:
            proto = path[0]
            schema_fields = {k: v for k, v in _CONTACT_SCHEMA.get(proto, {}).items() if not k.startswith("__")}
            entries = node if isinstance(node, dict) else {}
            merged_proto = {
                entry_name: _merge_entry(details, schema_fields)
                for entry_name, details in entries.items()
                if isinstance(details, dict)
            }
            flat = _flatten(merged_proto, dotted)
        else:
            proto = path[0]
            schema_fields = {k: v for k, v in _CONTACT_SCHEMA.get(proto, {}).items() if not k.startswith("__")}
            merged_entry = _merge_entry(node, schema_fields)
            flat = _flatten(merged_entry, dotted)

        t = Table(show_header=True, header_style="bold")
        t.add_column("Key", style="bold")
        t.add_column("Value")
        for key, val in flat:
            val_str = json.dumps(val) if isinstance(val, (list, dict)) else (str(val) if val is not None else "[dim]—[/dim]")
            t.add_row(key, val_str)
        if not flat:
            console.print("[dim](no entries)[/dim]")
        else:
            console.print(t)
        return

    if not path:
        # Top level: show all protocols with entry counts
        protocols = dict.fromkeys(list(_CONTACT_SCHEMA.keys()) + list(all_contacts.keys()))
        t = Table(show_header=True, header_style="bold")
        t.add_column("Protocol", style="bold")
        t.add_column("Entries", style="dim", justify="right")
        t.add_column("Description", style="dim")
        for proto in protocols:
            entries = all_contacts.get(proto, {})
            count = len(entries) if isinstance(entries, dict) else 0
            desc = _CONTACT_SCHEMA.get(proto, {}).get("__description__", "")
            t.add_row(proto, str(count) if count else "[dim]—[/dim]", desc)
        console.print(t)

    elif len(path) == 1:
        # Protocol level: show named entries with their key fields
        proto = path[0]
        schema_fields = {k: v for k, v in _CONTACT_SCHEMA.get(proto, {}).items() if not k.startswith("__")}
        entries = node if isinstance(node, dict) else {}
        if not entries:
            console.print("[dim](no entries)[/dim]")
            return
        t = Table(show_header=True, header_style="bold")
        t.add_column("Name", style="bold")
        for field in schema_fields:
            t.add_column(field.replace("_", " ").title())
        for entry_name, details in entries.items():
            if not isinstance(details, dict):
                continue
            row = [entry_name] + [
                str(details.get(f, "[dim]—[/dim]")) for f in schema_fields
            ]
            t.add_row(*row)
        console.print(t)

    else:
        # Named-entry level: show field-by-field with schema hints
        proto = path[0]
        schema_fields = {k: v for k, v in _CONTACT_SCHEMA.get(proto, {}).items() if not k.startswith("__")}
        entry = node if isinstance(node, dict) else {}
        all_keys = dict.fromkeys(list(schema_fields.keys()) + list(entry.keys()))
        t = Table(show_header=True, header_style="bold")
        t.add_column("Field", style="bold")
        t.add_column("Value")
        t.add_column("Description", style="dim")
        for field in all_keys:
            v = entry.get(field)
            val_str = json.dumps(v) if isinstance(v, (list, dict)) else (str(v) if v is not None else "[dim]—[/dim]")
            hint = schema_fields.get(field, {}).get("description", "") if isinstance(schema_fields.get(field), dict) else ""
            t.add_row(field, val_str, hint)
        console.print(t)


@contact_group.command("get")
@click.argument("path", nargs=-1, required=True)
@click.pass_obj
def contact_get(obj: dict, path: tuple[str, ...]) -> None:
    """Get a contact field value.

    Examples:

    \b
      udb contact get email work address
      udb contact get sms primary phone
    """
    if len(path) < 2:
        err.print("[red]Error:[/red] Provide at least protocol and name (e.g. email work).")
        sys.exit(1)
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        manager = source._get_manager(db)
        if len(path) == 2:
            proto, name = path
            value = manager.get_contact(proto, name)
        else:
            proto, name, *field_parts = path
            entry = manager.get_contact(proto, name)
            if entry is None:
                err.print(f"[red]Error:[/red] Contact {proto!r}/{name!r} not found.")
                sys.exit(1)
            value = entry
            for part in field_parts:
                if not isinstance(value, dict) or part not in value:
                    err.print(f"[red]Error:[/red] Field {part!r} not found.")
                    sys.exit(1)
                value = value[part]
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if value is None:
        err.print(f"[yellow]Not set:[/yellow] {'.'.join(path)}")
        sys.exit(1)
    if isinstance(value, (dict, list)):
        console.print_json(json.dumps(value))
    else:
        console.print(value)


@contact_group.command("set")
@click.argument("args", nargs=-1, required=True)
@click.pass_obj
def contact_set(obj: dict, args: tuple[str, ...]) -> None:
    """Set a contact field. Provide protocol, name, field, and value.

    Examples:

    \b
      udb contact set email work address alice@example.com
      udb contact set email work preference 0
      udb contact set sms primary phone +15550123
    """
    if len(args) < 4:
        err.print("[red]Error:[/red] Provide protocol, name, field, and value.")
        sys.exit(1)
    proto, name, *rest = args
    *field_parts, raw_value = rest
    field = ".".join(field_parts)
    value = _parse_metadata_value(raw_value)
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        source._get_manager(db).set_contact_field(proto, name, field, value)
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    display = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
    console.print(f"[green]Set[/green] {proto}.{name}.{field} = {display}")


@contact_group.command("add")
@click.argument("protocol")
@click.argument("name")
@click.option("--preference", "preference", default=0, type=int, show_default=True,
              help="Ordering priority (lower = preferred).")
@click.pass_obj
def contact_add(obj: dict, protocol: str, name: str, preference: int) -> None:
    """Create a named contact entry under a protocol.

    Set individual fields with `udb contact set` afterwards.

    Examples:

    \b
      udb contact add email work
      udb contact add sms primary --preference 1
    """
    if protocol not in _CONTACT_SCHEMA:
        err.print(f"[red]Error:[/red] Unknown protocol {protocol!r}. "
                  f"Known: {', '.join(_CONTACT_SCHEMA)}")
        sys.exit(1)
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        manager = source._get_manager(db)
        if manager.get_contact(protocol, name) is not None:
            err.print(f"[red]Error:[/red] Contact {protocol!r}/{name!r} already exists. "
                      "Use `udb contact set` to update fields.")
            sys.exit(1)
        manager.set_contact_field(protocol, name, "preference", preference)
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"[green]Added[/green] contact: [bold]{protocol}/{name}[/bold]")


@contact_group.command("remove")
@click.argument("protocol")
@click.argument("name")
@click.option("--yes", is_flag=True, default=False, help="Skip confirmation prompt.")
@click.pass_obj
def contact_remove(obj: dict, protocol: str, name: str, yes: bool) -> None:
    """Remove a named contact entry.

    Examples:

    \b
      udb contact remove email personal
    """
    if not yes:
        click.confirm(f"Remove contact {protocol!r}/{name!r}?", abort=True)
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        source._get_manager(db).delete_contact(protocol, name)
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"[green]Removed[/green] contact: [bold]{protocol}/{name}[/bold]")
