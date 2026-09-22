"""
FileUserSource end-to-end demo.

Covers the full operational shape of the file-backed UserSource:
  1. Create a user -- registry, KB, metadata, contacts, sessions all as JSON
     files on disk; metadata is auto-seeded from data/metadata_schema.json
  2. Set metadata, register a contact method, start a session
  3. add_source -- register a file for provenance AND extract facts into the
     KB from it (Type 2 import)
  4. Persistence -- a second FileUserSource instance pointed at the same
     data directory sees everything the first one wrote, with no explicit
     save step
  5. Query the reopened database

Run from examples/backends/:
    python3 file_backend_demo.py
"""
import asyncio
import shutil
import tempfile
from pathlib import Path

from blue_data_user_source import FileUserSource
from blue_data_user_source.data.manager import CLS_JSON_FILE, CLS_KB_FILE

DIVIDER = "-" * 60


def _file_json_props(path: Path) -> dict:
    return {"_class": CLS_JSON_FILE, "connection": {"protocol": "json/file", "path": str(path)}}


def _file_kb_props(directory: Path) -> dict:
    return {"_class": CLS_KB_FILE, "connection": {"protocol": "kb/file", "directory": str(directory)}}


async def main():
    tmp = Path(tempfile.mkdtemp(prefix="blue-userdb-file-backend-demo-"))
    print(f"Working directory: {tmp}")

    # ---------------------------------------------------------------- #
    # 1. Create a user -- everything file-backed
    # ---------------------------------------------------------------- #
    print()
    print(DIVIDER)
    print("1. Create user (file-backed registry, KB, metadata, contacts, sessions)")
    print(DIVIDER)

    outer = FileUserSource("blue-userdb", {"connection": {"path": str(tmp / "registry.json")}})
    await outer.create_user(
        "alice",
        registry_props=_file_json_props(tmp / "registries" / "alice.json"),
        kb_source_props=_file_kb_props(tmp / "sources" / "alice"),
        metadata_source_props=_file_json_props(tmp / "sources" / "alice" / "metadata.json"),
        contact_source_props=_file_json_props(tmp / "sources" / "alice" / "contacts.json"),
        session_source_props=_file_json_props(tmp / "sources" / "alice" / "sessions.json"),
    )
    seeded = outer.list_metadata("alice")
    print(f"Metadata auto-seeded from schema: {list(seeded.keys())} categories")
    print(f"  identity: {seeded['identity']}")

    # ---------------------------------------------------------------- #
    # 2. Metadata, contact method, session
    # ---------------------------------------------------------------- #
    print()
    print(DIVIDER)
    print("2. Set metadata, register a contact method, start a session")
    print(DIVIDER)

    outer.set_metadata("alice", "identity.name", "Alice")
    outer.set_metadata("alice", "identity.timezone", "America/New_York")
    outer.set_metadata("alice", "preferences.verbosity", "brief")
    await outer.add_contact_method(
        "alice", "stdio", "terminal", details={}, preference=0,
    )
    session_id = await outer.create_session("alice")
    print(f"Session created: {session_id}")

    # ---------------------------------------------------------------- #
    # 3. add_source -- provenance + LLM extraction into the KB
    # ---------------------------------------------------------------- #
    print()
    print(DIVIDER)
    print("3. add_source -- register a file and extract facts from it")
    print(DIVIDER)

    bio = tmp / "alice_bio.txt"
    bio.write_text("Alice is a data scientist who has worked at IBM for six years.")
    await outer.add_source(
        str(bio), "alice",
        optional_properties={
            "name": "Alice's bio",
            "queries": ["What is Alice's occupation and employer?"],
        },
    )
    sources = await outer.list_sources("alice")
    print(f"Sources registered in the KB: {[s.get('name') for s in sources]}")

    # ---------------------------------------------------------------- #
    # 4. Persistence -- a fresh instance sees the same data, no save step
    # ---------------------------------------------------------------- #
    print()
    print(DIVIDER)
    print("4. Persistence -- reopen the same directory with a new instance")
    print(DIVIDER)

    reopened = FileUserSource("blue-userdb", {"connection": {"path": str(tmp / "registry.json")}})
    print("Users visible after reopen:", reopened.list_users())
    print("Metadata survived:", {
        k: v for k, v in reopened.list_metadata("alice")["identity"].items() if v
    })
    contacts = await reopened.list_contact_methods("alice")
    print("Contact methods survived:", [(c.protocol, c.name) for c in contacts])
    sessions = await reopened.list_sessions("alice")
    print(f"Sessions survived: {list(sessions.keys()) == [session_id]}")

    # ---------------------------------------------------------------- #
    # 5. Query the reopened database
    # ---------------------------------------------------------------- #
    print()
    print(DIVIDER)
    print("5. Query the reopened database")
    print(DIVIDER)

    answer, qsession_id = await reopened.async_execute_query(
        "What does alice do for work?", database="alice",
        optional_properties={
            "session": session_id, "output_form": "nl", "max_interaction_rounds": 0,
        },
    )
    print(f"Answer (session {qsession_id}): {answer}")

    shutil.rmtree(tmp)
    print()
    print(f"Cleaned up {tmp}")
    print("Demo complete.")


asyncio.run(main())
