"""blue-data-user-source MCP server.

Exposes UserSource operations as MCP tools so LLM clients (Claude Desktop,
Claude Code, etc.) can manage per-user knowledge stores, run natural-language
queries, edit metadata, and handle contact methods.

Tool groups
-----------
Users (write)    — create_database, delete_database, reset_database
Users (read)     — list_databases, get_database
Query            — query
Sessions         — session_start, session_end, get_session, list_sessions
Data (write)     — add_source, remove_source
Data (read)      — list_data, list_sources
Metadata (write) — set_metadata, delete_metadata
Metadata (read)  — get_metadata, list_metadata
Contacts (write) — add_contact, update_contact, remove_contact
Contacts (read)  — list_contacts, get_contact

Quick start
-----------
    # Install
    pip install -e ../../lib
    pip install -e .

    # Run (stdio transport for Claude Desktop / Claude Code)
    blue-userdb-mcp

    # With a specific data directory
    BLUE_DATA_USER_SOURCE_DATA_DIR=/path/to/data blue-userdb-mcp

Claude Desktop config (~/.config/claude-desktop/claude_desktop_config.json):
    {
      "mcpServers": {
        "blue-data-user": {
          "command": "blue-userdb-mcp",
          "env": {
            "BLUE_DATA_USER_SOURCE_DATA_DIR": "/path/to/data"
          }
        }
      }
    }
"""
from __future__ import annotations

import json
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from blue_data_user_mcp.config import default_user_props, get_source

mcp = FastMCP(
    "blue-data-user",
    instructions=(
        "Per-user knowledge store — create users, ingest data sources, run natural-language "
        "queries, manage metadata and contact methods. Each user (database) has its own "
        "isolated knowledge graph, metadata, and contact list."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(e: Exception) -> str:
    return json.dumps({"error": str(e)}, indent=2)


# ---------------------------------------------------------------------------
# Users (write)
# ---------------------------------------------------------------------------

@mcp.tool()
async def create_database(name: str) -> str:
    """Create a new user database with file-backed storage under BLUE_DATA_USER_SOURCE_DATA_DIR.

    All storage paths (registry, KB, metadata, contacts) are derived
    automatically from the user name and the server's data directory. Use
    the REST API (POST /databases/{name}) to supply custom storage paths.

    Args:
        name: User name, e.g. 'alice'.
    """
    try:
        source = get_source()
        if name in source.list_users():
            # UserSource.create_user is permissive — it rebuilds the manager and
            # re-registers the record — so the guard lives here, as it does in
            # the CLI's `database create`.
            raise ValueError(f"Database '{name}' already exists.")
        props = default_user_props(name)
        await source.create_user(
            name,
            registry_props=props["registry"],
            kb_source_props=props["kb_source"],
            metadata_source_props=props["metadata_source"],
            contact_source_props=props["contact_source"],
            session_source_props=props["session_source"],
            doc_source_props=props["doc_source"],
            # `create_user` onboards by default, which prompts on the console.
            # A server has none: the prompts would go nowhere and the call would
            # block or read EOF. Onboarding belongs to the CLI.
            onboard=False,
            onboard_metadata=False,
        )
        return _ok({"name": name, "created": True})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def delete_database(name: str) -> str:
    """Delete a user and all their backing data files.

    Args:
        name: User name to delete.
    """
    try:
        await get_source().delete_user(name)
        return _ok({"name": name, "deleted": True})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def reset_database(name: str) -> str:
    """Clear a user's KB data and reseed the schema. Metadata and contacts are preserved.

    Args:
        name: User name to reset.
    """
    try:
        await get_source().reset_user(name)
        return _ok({"name": name, "reset": True})
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Users (read)
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_databases() -> str:
    """List all registered user names."""
    try:
        return _ok(get_source().list_users())
    except Exception as e:
        return _err(e)


@mcp.tool()
async def get_database(name: str) -> str:
    """Return registry properties for a user (storage paths, class, schema paths).

    Args:
        name: User name.
    """
    try:
        info = get_source().get_user(name)
        if info is None:
            return _err(ValueError(f"User {name!r} not found"))
        return _ok({"name": name, **info})
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

@mcp.tool()
async def query(
    user: str,
    question: str,
    output_form: str = "json",
    session: Optional[str] = None,
    include_expanded: bool = False,
) -> str:
    """Answer a natural-language question using the user's knowledge graph.

    Runs a multi-step agent that contextualises and expands the query,
    runs all sub-questions in parallel against the KB, assesses result
    quality, and optionally asks the user for clarification via their
    configured contact method.

    Args:
        user:             User name (database to query).
        question:         Natural-language question.
        output_form:      'json' (default — a single aggregated table of rows) or
                          'nl' (prose answer).
        session:          Optional session id for query context continuity.
        include_expanded: If True, also return the per-sub-question queries and
                          their raw results alongside the synthesized answer.
    """
    try:
        optional: dict[str, Any] = {"output_form": output_form}
        if session:
            optional["session"] = session
        if include_expanded:
            optional["include_expanded"] = True
        result, session_id = await get_source().async_execute_query(
            question, database=user, optional_properties=optional
        )
        return _ok({"results": result, "session_id": session_id})
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@mcp.tool()
async def session_start(user: str) -> str:
    """Create a new session for a user, so multiple queries can share context and history.

    Pass the returned session_id as the `session` argument to `query` calls
    to append them to this session instead of each getting an ad hoc one.

    Args:
        user: User name.
    """
    try:
        session_id = await get_source().create_session(user)
        return _ok({"user": user, "session_id": session_id})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def session_end(user: str, session_id: str) -> str:
    """End a session. Further queries cannot be appended to it.

    Args:
        user:       User name.
        session_id: Session to end.
    """
    try:
        await get_source().end_session(user, session_id)
        return _ok({"user": user, "session_id": session_id, "ended": True})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def get_session(user: str, session_id: str) -> str:
    """Get a session's queries and interactions.

    Args:
        user:       User name.
        session_id: Session to retrieve.
    """
    try:
        record = await get_source().get_session(user, session_id)
        if record is None:
            return _err(ValueError(f"Session {session_id!r} not found for {user!r}"))
        return _ok({"session_id": session_id, **record})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_sessions(user: str) -> str:
    """List all sessions for a user.

    Args:
        user: User name.
    """
    try:
        return _ok(await get_source().list_sessions(user))
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Data (write)
# ---------------------------------------------------------------------------

@mcp.tool()
async def add_source(
    user: str,
    source: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    original: Optional[str] = None,
    queries: Optional[list[str]] = None,
) -> str:
    """Register a data source for a user and optionally ingest its content.

    Without queries, the source is registered for provenance only (Type 1).
    With queries, an LLM agent extracts attributes guided by those questions
    and stores the results in the KB (Type 2).

    Args:
        user:        User name.
        source:      Free text or a file path identifying the source.
        name:        Human-readable source label (defaults to source).
        description: Optional description.
        original:    The source's own date (e.g. publication date).
        queries:     Guiding questions to focus extraction (optional).
    """
    try:
        props: dict[str, Any] = {}
        if name:
            props["name"] = name
        if description:
            props["description"] = description
        if original:
            props["original"] = original
        if queries:
            props["queries"] = queries
        await get_source().add_source(source, database=user, optional_properties=props)
        return _ok({"user": user, "source": source, "added": True})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def remove_source(user: str, source_name: str) -> str:
    """Remove a source from the user's registry. KB data is preserved.

    Args:
        user:        User name.
        source_name: Name of the source to remove.
    """
    try:
        source = get_source()
        # UserDataManager.remove_source returns silently when nothing matches,
        # so without this the tool reports removed:True for a source that was
        # never there.
        known = {s.get("name") for s in await source.list_sources(user)}
        if source_name not in known:
            raise ValueError(f"Source '{source_name}' is not registered for user '{user}'.")
        source.remove_source(user, source_name)
        return _ok({"user": user, "source": source_name, "removed": True})
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Data (read)
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_data(user: str) -> str:
    """List all ingested data entries in a user's knowledge graph.

    Args:
        user: User name.
    """
    try:
        entries = await get_source().list_data(user)
        return _ok(entries)
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_sources(user: str, source_id: Optional[str] = None) -> str:
    """List registered sources for a user.

    Args:
        user:      User name.
        source_id: Optional source id to retrieve a single source.
    """
    try:
        entries = await get_source().list_sources(user, source_id)
        return _ok(entries)
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Metadata (write)
# ---------------------------------------------------------------------------

@mcp.tool()
async def set_metadata(user: str, key: str, value: Any) -> str:
    """Set a metadata value for a user. Supports nested keys with '.' separator.

    Common keys: identity.name, identity.email, preferences.verbosity,
    preferences.language, availability.preferred_channel, privacy.consent_level.

    Args:
        user:  User name.
        key:   Dot-separated metadata key, e.g. 'preferences.verbosity'.
        value: Value to store (string, number, boolean, list, or dict).
    """
    try:
        get_source().set_metadata(user, key, value)
        return _ok({"user": user, "key": key, "value": value})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def delete_metadata(user: str, key: str) -> str:
    """Delete a metadata key for a user.

    Args:
        user: User name.
        key:  Dot-separated metadata key to delete.
    """
    try:
        get_source().delete_metadata(user, key)
        return _ok({"user": user, "key": key, "deleted": True})
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Metadata (read)
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_metadata(user: str, key: str) -> str:
    """Get a single metadata value for a user.

    Args:
        user: User name.
        key:  Dot-separated metadata key, e.g. 'preferences.verbosity'.
    """
    try:
        value = get_source().get_metadata(user, key)
        if value is None:
            return _err(KeyError(f"Metadata key {key!r} not found for {user!r}"))
        return _ok({"user": user, "key": key, "value": value})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_metadata(user: str) -> str:
    """List all metadata key-value pairs for a user.

    Args:
        user: User name.
    """
    try:
        return _ok(get_source().list_metadata(user))
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Contacts (write)
# ---------------------------------------------------------------------------

@mcp.tool()
async def add_contact(
    user: str,
    protocol: str,
    name: str,
    details: dict[str, Any],
    preference: int = 0,
) -> str:
    """Add a contact method for a user.

    Supported protocols: 'email', 'slack', 'sms', 'webhook'.

    Args:
        user:       User name.
        protocol:   Contact protocol, e.g. 'email', 'webhook'.
        name:       Human-readable label for this contact method.
        details:    Protocol-specific details dict.
                    email   → {"address": "alice@example.com"}
                    slack   → {"channel": "#alice", "token": "..."}
                    webhook → {"url": "...", "response_base_url": "http://...", "timeout": 300}
        preference: Ordering priority (lower = higher priority, default 0).
    """
    try:
        await get_source().add_contact_method(user, protocol, name, details, preference)
        return _ok({"user": user, "protocol": protocol, "name": name, "added": True})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def update_contact(
    user: str,
    protocol: str,
    name: str,
    details: Optional[dict[str, Any]] = None,
    preference: Optional[int] = None,
) -> str:
    """Update details or preference for an existing contact method.

    Args:
        user:       User name.
        protocol:   Contact protocol.
        name:       Contact method label.
        details:    New details dict (replaces existing if provided).
        preference: New preference ordering (replaces existing if provided).
    """
    try:
        updates: dict[str, Any] = {}
        if details is not None:
            updates["details"] = details
        if preference is not None:
            updates["preference"] = preference
        await get_source().update_contact_method(user, protocol, name, **updates)
        return _ok({"user": user, "protocol": protocol, "name": name, "updated": True})
    except Exception as e:
        return _err(e)


@mcp.tool()
async def remove_contact(user: str, protocol: str, name: str) -> str:
    """Remove a contact method from a user.

    Args:
        user:     User name.
        protocol: Contact protocol.
        name:     Contact method label.
    """
    try:
        await get_source().remove_contact_method(user, protocol, name)
        return _ok({"user": user, "protocol": protocol, "name": name, "removed": True})
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Contacts (read)
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_contacts(user: str, protocol: Optional[str] = None) -> str:
    """List contact methods for a user.

    Args:
        user:     User name.
        protocol: Optional protocol filter, e.g. 'email'.
    """
    try:
        methods = await get_source().list_contact_methods(user, protocol)
        return _ok([m.__dict__ for m in methods])
    except Exception as e:
        return _err(e)


@mcp.tool()
async def get_contact(user: str, protocol: str, name: str) -> str:
    """Get a specific contact method for a user.

    Args:
        user:     User name.
        protocol: Contact protocol.
        name:     Contact method label.
    """
    try:
        method = await get_source().get_contact_method(user, protocol, name)
        if method is None:
            return _err(ValueError(f"Contact {protocol}/{name!r} not found for {user!r}"))
        return _ok(method.__dict__)
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
