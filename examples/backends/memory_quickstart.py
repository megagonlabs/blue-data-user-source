"""
Minimal in-memory quickstart: create a user, add data, query it.

No persistence -- the smallest useful UserSource example. Needs OPENAI_API_KEY:
UserQueryReasoner rewrites/expands the query, and KBSource.answer() drives its
own LLM tool-call loop to extract and retrieve data.

Run from examples/backends/:
    python3 memory_quickstart.py
"""
import asyncio
import shutil
import tempfile
from pathlib import Path

from blue_data_user_source import MemoryUserSource
from blue_data_user_source.data.manager import CLS_JSON_MEMORY, CLS_KB_MEMORY

_MEM_JSON = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}


async def main():
    us = MemoryUserSource("quickstart")
    await us.create_user(
        "alice",
        registry_props=_MEM_JSON,
        kb_source_props=_MEM_KB,
        metadata_source_props=_MEM_JSON,
        contact_source_props=_MEM_JSON,
        session_source_props=_MEM_JSON,
    )
    us.set_metadata("alice", "identity.name", "Alice")

    tmp = Path(tempfile.mkdtemp(prefix="blue-userdb-quickstart-"))
    bio = tmp / "alice_bio.txt"
    bio.write_text("Alice is a data scientist who has worked at IBM for six years.")
    await us.add_source(
        str(bio), "alice",
        optional_properties={"queries": ["What is Alice's occupation and employer?"]},
    )
    shutil.rmtree(tmp)

    # max_interaction_rounds=0: keep this quickstart non-interactive -- see
    # feature-demos/query_rewrite_demo.py and scenario-demos for the
    # clarification loop this skips (freshly-extracted facts carry no
    # provenance timestamp, so the freshness metric would otherwise fail and
    # trigger a stdio clarification prompt).
    answer, session_id = await us.async_execute_query(
        "What does alice do for work?", database="alice",
        optional_properties={"output_form": "nl", "max_interaction_rounds": 0},
    )
    print(f"Session: {session_id}")
    print("Answer:", answer)


asyncio.run(main())
