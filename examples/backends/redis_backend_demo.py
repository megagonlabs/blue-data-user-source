"""
RedisUserSource end-to-end demo.

blue-data-user-source has no Redis-backed KBSource (blue_data_kb_source only
ships memory/file/neo4j KB backends), so this demo's knowledge graph is
memory-backed; only the registry, metadata, contacts, and sessions layers --
UserSource's actual storage axis -- are Redis-backed here.

Uses Redis logical database 15 (RedisJSONSource's connection.db), isolated
from whatever else lives on the shared Redis instance's default database, and
flushes only that database when done -- safe to run against a shared Redis
instance without touching its other data.

Covers the same shape as file_backend_demo.py: create a user, set metadata,
register a contact, start a session, then reopen with a second RedisUserSource
instance pointed at the same Redis database and verify everything survived.

A real gotcha surfaced while writing this demo: RedisJSONSource.get() on a
JSONPath that doesn't exist yet returns an empty list, not None. seed_metadata_
schema/seed_contact_schema use "is None" to decide whether a category is
already seeded, so once the *first* schema category exists, every later
category's (non-None) `[]` reads as "already there" and is skipped -- only
`identity` (metadata) and `email` (contacts, seeded as an empty bucket) end up
present. This demo works within that: it only touches `identity.*` metadata
and an `email` contact method, both of which fully round-trip. See
file_backend_demo.py for the complete 4-category-metadata / 8-protocol-contact
picture, which the file JSON backend seeds correctly.

Run from examples/backends/ (needs a reachable Redis with the RedisJSON module,
e.g. `docker run -p 6379:6379 redis/redis-stack`):
    python3 redis_backend_demo.py
"""
import asyncio

import redis

from blue_data_user_source import RedisUserSource
from blue_data_user_source.data.manager import CLS_JSON_REDIS, CLS_KB_MEMORY

DIVIDER = "-" * 60
_DB = 15  # isolated from the shared instance's default database (0)
_NAMESPACE = "blue-userdb-examples-redis-backend-demo"


def _redis_json_props(namespace: str) -> dict:
    return {
        "_class": CLS_JSON_REDIS,
        "connection": {"protocol": "json/redis", "host": "localhost", "port": 6379, "db": _DB},
        "namespace": namespace,
    }


_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}


async def main():
    # ---------------------------------------------------------------- #
    # 1. Create a user -- Redis-backed registry/metadata/contacts/sessions
    # ---------------------------------------------------------------- #
    print(DIVIDER)
    print("1. Create user (Redis-backed registry, metadata, contacts, sessions)")
    print(DIVIDER)

    outer = RedisUserSource("blue-userdb", {
        "connection": {"host": "localhost", "port": 6379, "db": _DB},
        "registry": _redis_json_props(f"{_NAMESPACE}:outer"),
    })
    await outer.create_user(
        "alice",
        registry_props=_redis_json_props(f"{_NAMESPACE}:alice-registry"),
        kb_source_props=_MEM_KB,
        metadata_source_props=_redis_json_props(f"{_NAMESPACE}:alice-metadata"),
        contact_source_props=_redis_json_props(f"{_NAMESPACE}:alice-contacts"),
        session_source_props=_redis_json_props(f"{_NAMESPACE}:alice-sessions"),
        # These demos are non-interactive: create_user onboards by default,
        # which would prompt on stdin and make the captured output unreproducible.
        onboard=False,
        onboard_metadata=False,
    )
    seeded = outer.list_metadata("alice")
    print(f"Metadata categories present after seeding: {list(seeded.keys())}")
    print("(only 'identity' -- see the module docstring for why the other three don't land)")

    # ---------------------------------------------------------------- #
    # 2. Metadata, contact method, session
    # ---------------------------------------------------------------- #
    print()
    print(DIVIDER)
    print("2. Set metadata, register a contact method, start a session")
    print(DIVIDER)

    outer.set_metadata("alice", "identity.name", "Alice")
    outer.set_metadata("alice", "identity.timezone", "America/New_York")
    # "email" is the one contact protocol bucket schema-seeding actually
    # created (see module docstring) -- a new nested key under an *existing*
    # object round-trips fine.
    await outer.add_contact_method(
        "alice", "email", "work", details={"address": "alice@example.com"}, preference=0,
    )
    session_id = await outer.create_session("alice")
    print(f"Session created: {session_id}")

    # ---------------------------------------------------------------- #
    # 3. Persistence -- a fresh instance sees the same data, no save step
    # ---------------------------------------------------------------- #
    print()
    print(DIVIDER)
    print("3. Persistence -- reopen with a second RedisUserSource instance")
    print(DIVIDER)

    reopened = RedisUserSource("blue-userdb", {
        "connection": {"host": "localhost", "port": 6379, "db": _DB},
        "registry": _redis_json_props(f"{_NAMESPACE}:outer"),
    })
    print("Users visible after reopen:", reopened.list_users())
    print("Metadata survived:", {
        k: v for k, v in reopened.list_metadata("alice")["identity"].items() if v
    })
    contacts = await reopened.list_contact_methods("alice")
    print("Contact methods survived:", [(c.protocol, c.name) for c in contacts])
    sessions = await reopened.list_sessions("alice")
    print(f"Sessions survived: {list(sessions.keys()) == [session_id]}")

    # ---------------------------------------------------------------- #
    # 4. Clean up -- flush only the isolated demo database
    # ---------------------------------------------------------------- #
    redis.Redis(host="localhost", port=6379, db=_DB).flushdb()
    print()
    print(f"Flushed Redis db={_DB} (this demo's isolated database)")
    print("Demo complete.")


asyncio.run(main())
