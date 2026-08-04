from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from blue_data_user_source import FileSource, UserDbError, UserSource

_DEFAULT_DATA_DIR = Path.home() / ".userdb"

_console = Console()
_err = Console(stderr=True)


def _make_source(data_dir: Path, schema_path: Path | None = None) -> UserSource:
    """Build a UserSource backed by files under *data_dir*."""
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


@click.group()
@click.option(
    "--user",
    envvar="USERDB_USER",
    default=None,
    help="User name. Overrides USERDB_USER env var.",
)
@click.option(
    "--data-dir",
    envvar="USERDB_DATA_DIR",
    default=str(_DEFAULT_DATA_DIR),
    show_default=True,
    help="Directory where user data is stored. Overrides USERDB_DATA_DIR env var.",
    type=click.Path(path_type=Path),
)
@click.option(
    "--schema-path",
    envvar="USERDB_SCHEMA_PATH",
    default=None,
    help="Path to schema.json for KB schema seeding. Overrides USERDB_SCHEMA_PATH env var.",
    type=click.Path(exists=True, path_type=Path),
)
@click.pass_context
def cli(ctx: click.Context, user: str | None, data_dir: Path, schema_path: Path | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["user"] = user
    ctx.obj["data_dir"] = data_dir
    ctx.obj["schema_path"] = schema_path


@cli.command("query")
@click.argument("text")
@click.option("--session", default=None, help="Session ID for query context.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["table", "json", "nl"]),
    default="table",
    show_default=True,
)
@click.option("--top-k", "top_k", default=10, type=int)
@click.pass_context
def query_cmd(
    ctx: click.Context,
    text: str,
    session: str | None,
    fmt: str,
    top_k: int,
) -> None:
    """Execute a natural language query against a user database."""
    user = ctx.obj.get("user")
    if not user:
        _err.print("[red]Error:[/red] --user is required for this command.")
        sys.exit(1)
    source = _make_source(ctx.obj["data_dir"], ctx.obj.get("schema_path"))
    props: dict[str, Any] = {"top_k": top_k}
    if session:
        props["session"] = session
    if fmt == "nl":
        props["output_form"] = "nl"
    try:
        results = asyncio.run(source.execute_query(text, database=user, optional_properties=props))
    except UserDbError as exc:
        _err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    if fmt == "nl":
        click.echo(results)
    elif fmt == "json":
        click.echo(
            json.dumps(
                [{"query": r.query, "results": r.results} for r in results],  # type: ignore[union-attr]
                indent=2,
            )
        )
    else:
        table = Table()
        table.add_column("Query", style="cyan")
        table.add_column("Results")
        for r in results:  # type: ignore[union-attr]
            table.add_row(r.query, ", ".join(str(x) for x in r.results))
        _console.print(table)


@cli.command("import")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--query",
    "queries",
    multiple=True,
    help="Query to run over the file (Type 2 import). May be repeated.",
)
@click.pass_context
def import_cmd(ctx: click.Context, file: Path, queries: tuple[str, ...]) -> None:
    """Import a file into a user database."""
    user = ctx.obj.get("user")
    if not user:
        _err.print("[red]Error:[/red] --user is required for this command.")
        sys.exit(1)
    source = _make_source(ctx.obj["data_dir"], ctx.obj.get("schema_path"))
    props: dict[str, Any] | None = {"queries": list(queries)} if queries else None
    try:
        asyncio.run(source.import_source(FileSource(file), database=user, optional_properties=props))
    except UserDbError as exc:
        _err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    if queries:
        n = len(queries)
        _console.print(f"Imported: {file} ({n} {'query' if n == 1 else 'queries'})")
    else:
        _console.print(f"Registered: {file}")


@cli.group("user")
def user_group() -> None:
    """Manage user databases."""


@user_group.command("create")
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
@click.pass_context
def user_create(
    ctx: click.Context,
    name: str,
    kb_backend: str,
    neo4j_uri: str | None,
    neo4j_user: str | None,
    neo4j_password: str | None,
) -> None:
    """Create a new user database."""
    data_dir: Path = ctx.obj["data_dir"]
    schema_path: Path | None = ctx.obj.get("schema_path")
    source = _make_source(data_dir, schema_path)

    if name in source.list_users():
        _err.print(f"[red]Error:[/red] User '{name}' already exists.")
        sys.exit(1)

    kb_extras: dict[str, Any] = {}
    if kb_backend == "neo4j":
        if not (neo4j_uri and neo4j_user and neo4j_password):
            _err.print("[red]Error:[/red] neo4j backend requires --neo4j-uri, --neo4j-user, --neo4j-password.")
            sys.exit(1)
        kb_extras = {"uri": neo4j_uri, "username": neo4j_user, "password": neo4j_password}

    registry_props = _user_registry_props(data_dir, name)
    kb_props = _user_kb_props(data_dir, kb_backend, **kb_extras)
    metadata_props = _user_metadata_props(data_dir, name)
    contact_props = _user_contact_props(data_dir, name)
    try:
        asyncio.run(source.create_user(name, registry_props, kb_props, metadata_props, contact_props))
    except UserDbError as exc:
        _err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    _console.print(f"Created user: {name}")


@user_group.command("delete")
@click.argument("name")
@click.pass_context
def user_delete(ctx: click.Context, name: str) -> None:
    """Delete a user database and all its KB data."""
    source = _make_source(ctx.obj["data_dir"])
    try:
        asyncio.run(source.delete_user(name))
    except UserDbError as exc:
        _err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    _console.print(f"Deleted user: {name}")


@user_group.command("reset")
@click.argument("name")
@click.pass_context
def user_reset(ctx: click.Context, name: str) -> None:
    """Clear KB data for a user and reseed the schema."""
    source = _make_source(ctx.obj["data_dir"], ctx.obj.get("schema_path"))
    try:
        asyncio.run(source.reset_user(name))
    except UserDbError as exc:
        _err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    _console.print(f"Reset user: {name}")


@user_group.command("ls")
@click.pass_context
def user_list(ctx: click.Context) -> None:
    """List all registered users."""
    source = _make_source(ctx.obj["data_dir"])
    names = source.list_users()
    if not names:
        return
    table = Table(show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Registry")
    for name in names:
        entry = source.get_user(name) or {}
        reg_backend = entry.get("registry", {}).get("backend", "memory")
        table.add_row(name, reg_backend)
    _console.print(table)


@user_group.group("show")
def show_group() -> None:
    """Show user database contents."""


@show_group.command("data")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["table", "json", "nl"]),
    default="table",
    show_default=True,
)
@click.pass_context
def show_data(ctx: click.Context, fmt: str) -> None:
    """Show data entries for the current user database."""
    user = ctx.obj.get("user")
    if not user:
        _err.print("[red]Error:[/red] --user is required for this command.")
        sys.exit(1)
    source = _make_source(ctx.obj["data_dir"])
    try:
        entries = asyncio.run(source.list_data(database=user))
    except UserDbError as exc:
        _err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if not entries:
        return
    if fmt == "json":
        click.echo(json.dumps(entries, indent=2))
    elif fmt == "nl":
        try:
            description = asyncio.run(source.describe_data(database=user))
        except UserDbError as exc:
            _err.print(f"[red]Error:[/red] {exc}")
            sys.exit(1)
        click.echo(description)
    else:
        table = Table(show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Value")
        for entry in entries:
            table.add_row(str(entry.get("name", "")), str(entry.get("value", "")))
        _console.print(table)


@show_group.command("metadata")
@click.argument("source_id", required=False, default=None)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["table", "json", "nl"]),
    default="table",
    show_default=True,
)
@click.pass_context
def show_metadata(ctx: click.Context, source_id: str | None, fmt: str) -> None:
    """Show source metadata for the current user database."""
    user = ctx.obj.get("user")
    if not user:
        _err.print("[red]Error:[/red] --user is required for this command.")
        sys.exit(1)
    source = _make_source(ctx.obj["data_dir"])
    try:
        entries = asyncio.run(source.list_metadata(database=user, source_id=source_id))
    except UserDbError as exc:
        _err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if not entries:
        return
    if fmt == "json":
        click.echo(json.dumps(entries, indent=2))
    elif fmt == "nl":
        try:
            description = asyncio.run(source.describe_metadata(database=user, source_id=source_id))
        except UserDbError as exc:
            _err.print(f"[red]Error:[/red] {exc}")
            sys.exit(1)
        click.echo(description)
    else:
        table = Table(show_header=True)
        table.add_column("Source ID", style="cyan")
        table.add_column("Location")
        for entry in entries:
            table.add_row(str(entry.get("id", "")), str(entry.get("location", "")))
        _console.print(table)
