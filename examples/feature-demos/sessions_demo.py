"""
Sessions -- reuse-or-create semantics for execute_query.

Omitting "session" from optional_properties auto-creates a new single-query
session. Passing an existing session id appends the query to that session
(raises QueryError if unknown or already ended). Once ended, no more queries
can be appended.

Run from examples/feature-demos/:
    python3 sessions_demo.py
"""
import asyncio

from blue_data_user_source import MemoryUserSource
from blue_data_user_source.data.manager import CLS_JSON_MEMORY, CLS_KB_MEMORY
from blue_data_user_source.types import QueryError

DIVIDER = "-" * 60
_MEM_JSON = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}
_OPTS = {"output_form": "nl", "max_interaction_rounds": 0}


async def main():
    us = MemoryUserSource("sessions-demo")
    await us.create_user(
        "alice",
        registry_props=_MEM_JSON, kb_source_props=_MEM_KB,
        metadata_source_props=_MEM_JSON, contact_source_props=_MEM_JSON,
        session_source_props=_MEM_JSON,
    )
    us.set_metadata("alice", "identity.name", "Alice")

    print(DIVIDER)
    print("1. No session id -- auto-creates a new single-query session")
    print(DIVIDER)
    _, session_a = await us.async_execute_query(
        "What is Alice's timezone?", database="alice", optional_properties=_OPTS,
    )
    _, session_b = await us.async_execute_query(
        "What is Alice's timezone?", database="alice", optional_properties=_OPTS,
    )
    print(f"  Query 1 landed in session: {session_a}")
    print(f"  Query 2 landed in session: {session_b}")
    print(f"  Different sessions (auto-create each time): {session_a != session_b}")

    print()
    print(DIVIDER)
    print("2. Explicit session id -- reused across queries")
    print(DIVIDER)
    _, reused = await us.async_execute_query(
        "What is Alice's occupation?", database="alice",
        optional_properties={**_OPTS, "session": session_a},
    )
    print(f"  Reused session id: {reused} (matches session_a: {reused == session_a})")
    record = await us.get_session("alice", session_a)
    print(f"  Queries recorded in session_a: {len(record['queries'])}")

    print()
    print(DIVIDER)
    print("3. Ending a session -- no more queries can be appended")
    print(DIVIDER)
    await us.end_session("alice", session_a)
    record = await us.get_session("alice", session_a)
    print(f"  session_a status: {record['status']}")
    try:
        await us.async_execute_query(
            "One more question", database="alice",
            optional_properties={**_OPTS, "session": session_a},
        )
    except QueryError as exc:
        print(f"  Querying an ended session raised QueryError: {exc}")

    print()
    print(DIVIDER)
    print("4. Querying an unknown session id also raises QueryError")
    print(DIVIDER)
    try:
        await us.async_execute_query(
            "Another question", database="alice",
            optional_properties={**_OPTS, "session": "does-not-exist"},
        )
    except QueryError as exc:
        print(f"  {exc}")


asyncio.run(main())
