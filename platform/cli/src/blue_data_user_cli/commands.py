import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from blue_data_user_source import FileSource, UserDbError, UserSource
from blue_data_user_source.backends.file import file_store_factory

_DEFAULT_DATA_DIR = Path.home() / ".userdb"

_console = Console()
_err = Console(stderr=True)


def _make_source(user: str | None, data_dir: Path, schema_path: Path | None = None) -> UserSource:
    props: dict[str, Any] = {"store_factory": file_store_factory(data_dir)}
    if user:
        props["database"] = user
    if schema_path:
        props["schema_path"] = str(schema_path)
    return UserSource(properties=props)


@click.group()
@click.option(
    "--user",
    envvar="USERDB_DATABASE",
    default=None,
    help="User database ID. Overrides USERDB_DATABASE env var.",
)
@click.option(
    "--data-dir",
    envvar="USERDB_DATA_DIR",
    default=str(_DEFAULT_DATA_DIR),
    show_default=True,
    help="Directory where database files are stored. Overrides USERDB_DATA_DIR env var.",
    type=click.Path(path_type=Path),
)
@click.option(
    "--schema-path",
    envvar="USERDB_SCHEMA_PATH",
    default=None,
    help="Path to schema reference file for attribute name generation. Overrides USERDB_SCHEMA_PATH env var.",
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
    help="Output format: table or json for structured results, nl for natural language.",
)
@click.pass_context
def query_cmd(ctx: click.Context, text: str, session: str | None, fmt: str) -> None:
    """Execute a natural language query against a user database."""
    source = _make_source(ctx.obj.get("user"), ctx.obj["data_dir"], ctx.obj.get("schema_path"))
    props: dict[str, Any] = {}
    if session:
        props["session"] = session
    if fmt == "nl":
        props["output_form"] = "nl"
    try:
        results = asyncio.run(source.execute_query(text, optional_properties=props or None))
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
    """Import a file into a user database.

    Omit --query to register the file as a source (Type 1).
    Provide --query to extract and store specific data (Type 2).
    """
    source = _make_source(ctx.obj.get("user"), ctx.obj["data_dir"], ctx.obj.get("schema_path"))
    props: dict[str, Any] | None = {"queries": list(queries)} if queries else None
    try:
        asyncio.run(source.import_source(FileSource(file), optional_properties=props))
    except UserDbError as exc:
        _err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    if queries:
        n = len(queries)
        label = "query" if n == 1 else "queries"
        _console.print(f"Imported: {file} ({n} {label})")
    else:
        _console.print(f"Registered: {file}")


@cli.group("user")
def user_group() -> None:
    """Manage user databases."""


@user_group.command("create")
@click.argument("name")
@click.pass_context
def database_create(ctx: click.Context, name: str) -> None:
    """Create a new user database."""
    source = _make_source(None, ctx.obj["data_dir"], ctx.obj.get("schema_path"))
    try:
        asyncio.run(source.create_database(name))
    except UserDbError as exc:
        _err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    _console.print(f"Created database: {name}")


@user_group.group("show")
def show_group() -> None:
    """Show user database contents."""


@show_group.command("data")
@click.argument("key", required=False, default=None)
@click.pass_context
def show_data(ctx: click.Context, key: str | None) -> None:
    """Show data entries for the current user database.

    Optionally filter by KEY (attribute name).
    """
    user = ctx.obj.get("user")
    if not user:
        _err.print("[red]Error:[/red] --user is required for this command.")
        sys.exit(1)
    source = _make_source(user, ctx.obj["data_dir"])
    try:
        entries = asyncio.run(source.list_data(key=key))
    except UserDbError as exc:
        _err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if not entries:
        return
    table = Table(show_header=True)
    table.add_column("Key", style="cyan")
    table.add_column("Values")
    table.add_column("Date")
    table.add_column("Source ID")
    for entry in entries:
        meta = entry.get("metadata") or {}
        values = ", ".join(str(v) for v in entry.get("value", []))
        table.add_row(
            str(entry.get("key", "")),
            values,
            str(meta.get("date", "")),
            str(meta.get("source_id", "")),
        )
    _console.print(table)


@show_group.command("metadata")
@click.argument("source_id", required=False, default=None)
@click.pass_context
def show_metadata(ctx: click.Context, source_id: str | None) -> None:
    """Show source metadata for the current user database.

    Optionally filter by SOURCE_ID.
    """
    user = ctx.obj.get("user")
    if not user:
        _err.print("[red]Error:[/red] --user is required for this command.")
        sys.exit(1)
    source = _make_source(user, ctx.obj["data_dir"])
    try:
        entries = asyncio.run(source.list_metadata(source_id=source_id))
    except UserDbError as exc:
        _err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if not entries:
        return
    table = Table(show_header=True)
    table.add_column("Source ID", style="cyan")
    table.add_column("Type")
    table.add_column("Location")
    table.add_column("Registered At")
    table.add_column("Queries")
    for entry in entries:
        queries = ", ".join(str(q) for q in entry.get("queries", []))
        table.add_row(
            str(entry.get("source_id", "")),
            str(entry.get("source_type", "")),
            str(entry.get("location", "")),
            str(entry.get("registered_at", "")),
            queries,
        )
    _console.print(table)


@user_group.command("ls")
@click.pass_context
def database_list(ctx: click.Context) -> None:
    """List all user databases."""
    data_dir: Path = ctx.obj["data_dir"]
    if not data_dir.exists():
        return
    databases = sorted(p.name for p in data_dir.iterdir() if p.is_dir())
    if not databases:
        return
    table = Table(show_header=True)
    table.add_column("Database", style="cyan")
    for name in databases:
        table.add_row(name)
    _console.print(table)
