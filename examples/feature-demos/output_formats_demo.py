"""
execute_query's output_form and include_expanded matrix.

The same question, answered three ways:
  - output_form="json"  -> a synthesized JSON table (list[dict])
  - output_form="nl"    -> a synthesized natural-language string
  - include_expanded=True (orthogonal to output_form) -> also returns the
    per-sub-question queries and their raw results alongside the answer, as
    {"result": ..., "expanded": ...}

Run from examples/feature-demos/:
    python3 output_formats_demo.py
"""
import asyncio
import shutil
import tempfile
from pathlib import Path

from blue_data_user_source import MemoryUserSource
from blue_data_user_source.data.manager import CLS_JSON_MEMORY, CLS_KB_MEMORY

DIVIDER = "-" * 60
_MEM_JSON = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}
_QUERY = "What does alice do for work, and where?"


async def main():
    us = MemoryUserSource("output-formats-demo")
    await us.create_user(
        "alice",
        registry_props=_MEM_JSON, kb_source_props=_MEM_KB,
        metadata_source_props=_MEM_JSON, contact_source_props=_MEM_JSON,
        session_source_props=_MEM_JSON,
    )
    us.set_metadata("alice", "identity.name", "Alice")

    tmp = Path(tempfile.mkdtemp(prefix="udb-output-formats-"))
    bio = tmp / "alice_bio.txt"
    bio.write_text("Alice is a data scientist at IBM, based in Austin, Texas.")
    await us.add_source(
        str(bio), "alice",
        optional_properties={"queries": ["What is Alice's occupation, employer, and location?"]},
    )
    shutil.rmtree(tmp)

    print(DIVIDER)
    print(f'1. output_form="json"  --  query: {_QUERY!r}')
    print(DIVIDER)
    answer, _ = await us.async_execute_query(
        _QUERY, database="alice",
        optional_properties={"output_form": "json", "max_interaction_rounds": 0},
    )
    print("Result type:", type(answer).__name__)
    print("Result:", answer)

    print()
    print(DIVIDER)
    print('2. output_form="nl"')
    print(DIVIDER)
    answer, _ = await us.async_execute_query(
        _QUERY, database="alice",
        optional_properties={"output_form": "nl", "max_interaction_rounds": 0},
    )
    print("Result type:", type(answer).__name__)
    print("Result:", answer)

    print()
    print(DIVIDER)
    print('3. include_expanded=True, output_form="json"')
    print(DIVIDER)
    answer, _ = await us.async_execute_query(
        _QUERY, database="alice",
        optional_properties={
            "output_form": "json", "include_expanded": True, "max_interaction_rounds": 0,
        },
    )
    print("Top-level keys:", sorted(answer.keys()))
    print("result:", answer["result"])
    print(f"expanded: {len(answer['expanded'])} sub-question/result pair(s)")
    for item in answer["expanded"]:
        print(f"  - Q: {item['query']!r}")
        print(f"    A: {item['results']}")

    print()
    print(DIVIDER)
    print('4. include_expanded=True, output_form="nl"')
    print(DIVIDER)
    answer, _ = await us.async_execute_query(
        _QUERY, database="alice",
        optional_properties={
            "output_form": "nl", "include_expanded": True, "max_interaction_rounds": 0,
        },
    )
    print("Top-level keys:", sorted(answer.keys()))
    print("result (prose):", answer["result"])
    print("expanded (prose):", answer["expanded"])


asyncio.run(main())
