"""
Metadata -- schema auto-seeding, get/set/delete, and per-topic availability overrides.

Metadata (identity, preferences, availability, privacy) is auto-seeded from
data/metadata_schema.json when a user is created, so every schema-defined key
is present (null) by default. availability.by_topic lets a project/topic
override working_hours/preferred_channel/out_of_office on top of the general
availability.* settings -- see contact_resolution_demo.py for how
ContactManager consumes it.

Run from examples/feature-demos/:
    python3 metadata_demo.py
"""
import asyncio

from blue_data_user_source import MemoryUserSource
from blue_data_user_source.data.manager import CLS_JSON_MEMORY, CLS_KB_MEMORY

DIVIDER = "-" * 60
_MEM_JSON = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}


async def main():
    us = MemoryUserSource("metadata-demo")
    await us.create_user(
        "alice",
        registry_props=_MEM_JSON, kb_source_props=_MEM_KB,
        metadata_source_props=_MEM_JSON, contact_source_props=_MEM_JSON,
        session_source_props=_MEM_JSON,
        # These demos are non-interactive: create_user onboards by default,
        # which would prompt on stdin and make the captured output unreproducible.
        onboard=False,
        onboard_metadata=False,
    )

    print(DIVIDER)
    print("1. Auto-seeded on creation -- every schema key present, null by default")
    print(DIVIDER)
    for category, entries in us.list_metadata("alice").items():
        print(f"  {category}: {entries}")

    print()
    print(DIVIDER)
    print("2. set_metadata / get_metadata")
    print(DIVIDER)
    us.set_metadata("alice", "identity.name", "Alice")
    us.set_metadata("alice", "identity.timezone", "America/New_York")
    us.set_metadata("alice", "preferences.verbosity", "brief")
    us.set_metadata("alice", "privacy.consent_level", "standard")
    print("  identity.name:", us.get_metadata("alice", "identity.name"))
    print("  preferences.verbosity:", us.get_metadata("alice", "preferences.verbosity"))
    print("  identity.pronouns (never set):", us.get_metadata("alice", "identity.pronouns"))

    print()
    print(DIVIDER)
    print("3. delete_metadata")
    print(DIVIDER)
    us.delete_metadata("alice", "preferences.verbosity")
    print("  preferences.verbosity after delete:", us.get_metadata("alice", "preferences.verbosity"))

    print()
    print(DIVIDER)
    print("4. availability.by_topic -- per-project overrides")
    print(DIVIDER)
    us.set_metadata("alice", "availability.working_hours", "09:00-17:00 Mon-Fri")
    us.set_metadata("alice", "availability.preferred_channel", "email")
    us.set_metadata("alice", "availability.by_topic", {
        "oncall": {"working_hours": "00:00-23:59 Mon-Sun", "preferred_channel": "webhook"},
    })
    print("  General availability.working_hours:", us.get_metadata("alice", "availability.working_hours"))
    print("  General availability.preferred_channel:", us.get_metadata("alice", "availability.preferred_channel"))
    print("  oncall override:", us.get_metadata("alice", "availability.by_topic.oncall"))
    print("  (no override for an unrelated topic:", us.get_metadata("alice", "availability.by_topic.marketing"), ")")


asyncio.run(main())
