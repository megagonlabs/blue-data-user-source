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


def _make_source(user: str | None, data_dir: Path) -> UserSource:
    props: dict[str, Any] = {"store_factory": file_store_factory(data_dir)}
    if user:
        props["database"] = user
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
@click.pass_context
def cli(ctx: click.Context, user: str | None, data_dir: Path) -> None:
    ctx.ensure_object(dict)
    ctx.obj["user"] = user
    ctx.obj["data_dir"] = data_dir


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
    source = _make_source(ctx.obj.get("user"), ctx.obj["data_dir"])
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
    source = _make_source(ctx.obj.get("user"), ctx.obj["data_dir"])
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
    source = _make_source(None, ctx.obj["data_dir"])
    try:
        asyncio.run(source.create_database(name))
    except UserDbError as exc:
        _err.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    _console.print(f"Created database: {name}")
