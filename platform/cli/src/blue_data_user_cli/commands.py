from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from blue_data_user_source import FileSource, FileUserSource, UDbError
from blue_data_user_source.data.manager import (
    CLS_JSON_FILE,
    CLS_JSON_MEMORY,
    CLS_KB_FILE,
    CLS_KB_MEMORY,
    CLS_KB_NEO4J,
)

_DEFAULT_DATA_DIR = Path.home() / ".udb"
_SELECTED_DB_FILE = ".selected.database"
_INTERNAL_SOURCES = {"kb", "metadata", "contacts"}

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


def _user_kb_props(data_dir: Path, name: str, kb_backend: str, **kb_extras: Any) -> dict:
    if kb_backend == "file":
        return {
            "_class": CLS_KB_FILE,
            "connection": {
                "protocol": "kb/file",
                "directory": str(data_dir / "sources" / name),
            },
        }
    if kb_backend == "memory":
        return {
            "_class": CLS_KB_MEMORY,
            "connection": {"protocol": "kb/memory"},
        }
    if kb_backend == "neo4j":
        return {
            "_class": CLS_KB_NEO4J,
            "connection": {"protocol": "kb/neo4j", **kb_extras},
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


# ------------------------------------------------------------------ #
# Root CLI                                                            #
# ------------------------------------------------------------------ #

@click.group()
@click.option(
    "--database",
    envvar="UDB_DATABASE",
    default=None,
    help="Database (user) name. Overrides UDB_DATABASE env var.",
)
@click.option(
    "--data-dir",
    envvar="UDB_DATA_DIR",
    default=str(_DEFAULT_DATA_DIR),
    show_default=True,
    help="Directory where user data is stored. Overrides UDB_DATA_DIR env var.",
    type=click.Path(path_type=Path),
)
@click.option(
    "--schema-path",
    envvar="UDB_SCHEMA_PATH",
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
@click.pass_obj
def database_create(
    obj: dict,
    name: str,
    kb_backend: str,
    neo4j_host: str,
    neo4j_port: int,
    neo4j_user: str,
    neo4j_password: str | None,
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
            _user_kb_props(data_dir, name, kb_backend, **kb_extras),
            _user_metadata_props(data_dir, name),
            _user_contact_props(data_dir, name),
        ))
    except UDbError as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"Created database: [bold]{name}[/bold]")


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
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show tool call arguments in the status line.")
@click.option("--log", "-l", is_flag=True, default=False, help="Log each tool call and result on its own line.")
@click.option("--log-limit", "log_limit", default=80, type=int, show_default=True, help="Truncation limit for logged values.")
@click.pass_obj
def data_query(
    obj: dict, text: str, session: str | None, fmt: str, top_k: int,
    verbose: bool, log: bool, log_limit: int,
) -> None:
    """Execute a natural-language query against the database."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    props: dict[str, Any] = {"top_k": top_k}
    if session:
        props["session"] = session
    if fmt == "nl":
        props["output_form"] = "nl"
    try:
        with console.status("Querying…") as status:
            on_tool_call, on_tool_result = _status_tool_callbacks(
                status, "Querying", verbose=verbose, log=log, log_limit=log_limit
            )
            props["on_tool_call"] = on_tool_call
            props["on_tool_result"] = on_tool_result
            results = source.execute_query(text, database=db, optional_properties=props)
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if fmt == "nl":
        click.echo(results)
        return
    if fmt == "json":
        click.echo(json.dumps(
            [{"query": r.query, "results": r.results} for r in results],  # type: ignore[union-attr]
            indent=2,
        ))
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("Query", style="cyan")
    t.add_column("Results")
    for r in results:  # type: ignore[union-attr]
        t.add_row(r.query, ", ".join(str(x) for x in r.results))
    console.print(t)


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
    help="Query to run over the file (Type 2 import). May be repeated.",
)
@click.option("--name", default=None, help="Human-readable label (defaults to source value).")
@click.option("--description", default=None, help="Optional description.")
@click.option("--original", default=None, help="Original date of the source (e.g. when it was published).")
@click.pass_obj
def source_add(obj: dict, file: Path, queries: tuple[str, ...], name: str | None, description: str | None, original: str | None) -> None:
    """Register a file as a data source and optionally ingest its content."""
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
    try:
        asyncio.run(source.add_source(FileSource(file), database=db, optional_properties=props or None))
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    label = name or str(file)
    if queries:
        n = len(queries)
        console.print(f"Added source: [bold]{label}[/bold] ({n} {'query' if n == 1 else 'queries'})")
    else:
        console.print(f"Registered source: [bold]{label}[/bold]")


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
      udb metadata get policy auto_approve
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
      udb metadata set policy auto_approve '["read","draft"]'
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
      udb metadata delete credentials github
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
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table", show_default=True)
@click.pass_obj
def contact_list(obj: dict, path: tuple[str, ...], fmt: str) -> None:
    """List contacts at the given path, or all protocols if no path given.

    Examples:

    \b
      udb contact list
      udb contact list email
      udb contact list email work
    """
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        all_contacts: dict = source._get_manager(db).get_contacts()
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    node: Any = all_contacts
    for i, segment in enumerate(path):
        if not isinstance(node, dict) or segment not in node:
            # Known schema protocol with no entries yet
            if i == 0 and segment in _CONTACT_SCHEMA:
                node = {}
                break
            err.print(f"[red]Error:[/red] Key not found: {'.'.join(path)!r}")
            sys.exit(1)
        node = node[segment]

    if fmt == "json":
        console.print_json(json.dumps(node))
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
