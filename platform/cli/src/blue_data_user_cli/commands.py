from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from blue_data_user_source import FileSource, UDbError, UserSource

_DEFAULT_DATA_DIR = Path.home() / ".udb"
_SELECTED_DB_FILE = ".selected.database"

console = Console()
err = Console(stderr=True)


def _make_source(data_dir: Path, schema_path: Path | None = None) -> UserSource:
    data_dir.mkdir(parents=True, exist_ok=True)
    return UserSource({
        "store": {"backend": "file", "path": str(data_dir / "db.json")},
        "schema": str(schema_path) if schema_path else None,
    })


def _user_registry_props(data_dir: Path, name: str) -> dict:
    return {"backend": "file", "path": str(data_dir / "registries" / f"{name}.json")}


def _user_kb_props(data_dir: Path, kb_backend: str, **kb_extras: Any) -> dict:
    props: dict[str, Any] = {"backend": kb_backend}
    if kb_backend == "file":
        props["directory"] = str(data_dir / "kb")
    props.update(kb_extras)
    return props


def _user_metadata_props(data_dir: Path, name: str) -> dict:
    return {"backend": "file", "path": str(data_dir / "sources" / f"{name}.metadata.json")}


def _user_contact_props(data_dir: Path, name: str) -> dict:
    return {"backend": "file", "path": str(data_dir / "sources" / f"{name}.contacts.json")}


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
    t.add_column("Registry Backend", style="dim")
    t.add_column("", max_width=3)
    for name in names:
        entry = source.get_user(name) or {}
        reg_backend = entry.get("registry", {}).get("backend", "memory")
        marker = "[green]*[/green]" if name == selected else ""
        t.add_row(name, reg_backend, marker)
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
@click.option("--neo4j-uri", default=None, help="Neo4j bolt URI (neo4j backend only).")
@click.option("--neo4j-user", default=None, help="Neo4j username.")
@click.option("--neo4j-password", default=None, help="Neo4j password.")
@click.pass_obj
def database_create(
    obj: dict,
    name: str,
    kb_backend: str,
    neo4j_uri: str | None,
    neo4j_user: str | None,
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
        if not (neo4j_uri and neo4j_user and neo4j_password):
            err.print("[red]Error:[/red] neo4j backend requires --neo4j-uri, --neo4j-user, --neo4j-password.")
            sys.exit(1)
        kb_extras = {"uri": neo4j_uri, "username": neo4j_user, "password": neo4j_password}

    try:
        asyncio.run(source.create_user(
            name,
            _user_registry_props(data_dir, name),
            _user_kb_props(data_dir, kb_backend, **kb_extras),
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
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
)
@click.pass_obj
def data_list(obj: dict, show_provenance: bool, fmt: str) -> None:
    """List all entities, property values, and facts in the database."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        manager = source._get_manager(db)
        kb = manager._ensure_kb_source()
        rows: list[dict] = asyncio.run(
            kb.fetch_database_data(db, include_provenance=show_provenance, compact=True)
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

    if entities:
        t = Table(title="Entities", show_header=True, header_style="bold")
        t.add_column("Name", style="bold")
        t.add_column("Class", style="dim")
        if show_provenance:
            t.add_column("Provenance", style="dim")
        for r in sorted(entities, key=lambda x: (x.get("class_name") or "", x.get("entity_name") or "")):
            row = [r.get("entity_name") or "", r.get("class_name") or ""]
            if show_provenance:
                row.append(r.get("extraction", "") or "")
            t.add_row(*row)
        console.print(t)

    if ent_props:
        t = Table(title="Entity Property Values", show_header=True, header_style="bold")
        t.add_column("Entity", style="bold")
        t.add_column("Property", style="dim")
        t.add_column("Value")
        if show_provenance:
            t.add_column("Provenance", style="dim")
        for r in sorted(ent_props, key=lambda x: (x.get("entity_name") or "", x.get("property_name") or "")):
            row = [r.get("entity_name") or "", r.get("property_name") or "", str(r.get("property_value", ""))]
            if show_provenance:
                row.append(r.get("extraction", "") or "")
            t.add_row(*row)
        console.print(t)

    if facts:
        t = Table(title="Facts", show_header=True, header_style="bold")
        t.add_column("Head", style="bold")
        t.add_column("Relation", style="dim")
        t.add_column("Tail", style="bold")
        if show_provenance:
            t.add_column("Provenance", style="dim")
        for r in sorted(facts, key=lambda x: (x.get("relation_name") or "", x.get("source_name") or "")):
            row = [r.get("source_name") or "", r.get("relation_name") or "", r.get("target_name") or ""]
            if show_provenance:
                row.append(r.get("extraction", "") or "")
            t.add_row(*row)
        console.print(t)

    if fact_props:
        t = Table(title="Fact Property Values", show_header=True, header_style="bold")
        t.add_column("Head", style="bold")
        t.add_column("Relation", style="dim")
        t.add_column("Tail", style="bold")
        t.add_column("Property", style="dim")
        t.add_column("Value")
        if show_provenance:
            t.add_column("Provenance", style="dim")
        for r in sorted(fact_props, key=lambda x: (x.get("relation_name") or "", x.get("head_name") or "", x.get("property_name") or "")):
            row = [
                r.get("head_name") or "",
                r.get("relation_name") or "",
                r.get("tail_name") or "",
                r.get("property_name") or "",
                str(r.get("property_value", "")),
            ]
            if show_provenance:
                row.append(r.get("extraction", "") or "")
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
@click.pass_obj
def data_query(obj: dict, text: str, session: str | None, fmt: str, top_k: int) -> None:
    """Execute a natural-language query against the database."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    props: dict[str, Any] = {"top_k": top_k}
    if session:
        props["session"] = session
    if fmt == "nl":
        props["output_form"] = "nl"
    try:
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
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show tool call arguments.")
@click.pass_obj
def data_extract(
    obj: dict,
    text: str,
    queries: tuple[str, ...],
    source_name: str | None,
    model: str,
    verbose: bool,
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
        asyncio.run(kb.import_text(
            db, text,
            queries=list(queries) or None,
            model=model,
            source_id=source_id,
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
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
)
@click.pass_obj
def source_list(obj: dict, fmt: str) -> None:
    """List data sources.

    Shows all registry sources and KG SOURCE nodes.
    Sources present in the KG but removed from the registry are marked (*).
    """
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    try:
        manager = source._get_manager(db)
        reg_records = manager._registry.list_records(record_type="source", scope="/") or []
        reg_names = {r.get("name") for r in reg_records}
        kg_sources = asyncio.run(manager.list_sources())
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    rows: list[dict] = [
        {"name": r.get("name", ""), "location": "", "in_registry": True}
        for r in reg_records
    ]
    for ks in kg_sources:
        name = ks.get("name", ks.get("id", ""))
        if name not in reg_names:
            rows.append({
                "name": name,
                "location": ks.get("source", ks.get("location", "")),
                "in_registry": False,
            })

    if fmt == "json":
        console.print_json(json.dumps(rows))
        return
    if not rows:
        console.print("[dim](no sources)[/dim]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("Name", style="bold")
    t.add_column("Location", style="dim")
    t.add_column("", max_width=5)
    for row in rows:
        marker = "[dim](*)[/dim]" if not row["in_registry"] else ""
        t.add_row(row["name"], row["location"], marker)
    console.print(t)


@source_group.command("add")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--query", "queries",
    multiple=True,
    help="Query to run over the file (Type 2 import). May be repeated.",
)
@click.pass_obj
def source_add(obj: dict, file: Path, queries: tuple[str, ...]) -> None:
    """Register a file as a data source and optionally ingest its content."""
    db = _get_db(obj)
    source = _make_source(obj["data_dir"])
    props: dict[str, Any] | None = {"queries": list(queries)} if queries else None
    try:
        asyncio.run(source.add_source(FileSource(file), database=db, optional_properties=props))
    except (UDbError, Exception) as exc:
        err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if queries:
        n = len(queries)
        console.print(f"Added source: [bold]{file}[/bold] ({n} {'query' if n == 1 else 'queries'})")
    else:
        console.print(f"Registered source: [bold]{file}[/bold]")


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
