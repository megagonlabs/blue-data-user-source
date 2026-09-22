"""
add_source -- provenance-only registration (Type 1) vs. LLM extraction (Type 2).

Every add_source call registers the file as a SOURCE node in the KB and always
ingests it (parsed, chunked, embedded) into the shared "external_documents"
DocumentDataSource, so it's searchable. Passing `queries` additionally drives
LLM extraction (import_text) into the KB graph for each query -- Type 2 import.
Without `queries`, the file is registered for provenance only (Type 1) -- its
text is searchable, but no facts are extracted into the KB graph.

Run from examples/feature-demos/:
    python3 add_source_provenance_demo.py
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


async def main():
    us = MemoryUserSource("provenance-demo")
    await us.create_user(
        "alice",
        registry_props=_MEM_JSON, kb_source_props=_MEM_KB,
        metadata_source_props=_MEM_JSON, contact_source_props=_MEM_JSON,
        session_source_props=_MEM_JSON,
    )
    us.set_metadata("alice", "identity.name", "Alice")

    tmp = Path(tempfile.mkdtemp(prefix="blue-userdb-provenance-demo-"))

    print(DIVIDER)
    print("1. Type 1 -- provenance-only registration (no `queries`)")
    print(DIVIDER)
    resume = tmp / "resume.txt"
    resume.write_text("Alice Smith -- Senior Data Scientist. 10 years experience in ML.")
    await us.add_source(str(resume), "alice", optional_properties={"name": "Alice's résumé"})
    sources = await us.list_sources("alice")
    print(f"  Sources registered in the KB: {[s.get('name') for s in sources]}")
    print("  No `queries` passed -- nothing extracted into the KB graph yet.")

    print()
    print(DIVIDER)
    print("2. Type 2 -- registration + LLM extraction (`queries` passed)")
    print(DIVIDER)
    bio = tmp / "bio.txt"
    bio.write_text("Alice has worked at IBM as a data scientist for six years.")
    await us.add_source(
        str(bio), "alice",
        optional_properties={
            "name": "Alice's bio",
            "queries": ["What is Alice's occupation and employer?"],
        },
    )
    sources = await us.list_sources("alice")
    print(f"  Sources registered in the KB: {[s.get('name') for s in sources]}")

    print()
    print(DIVIDER)
    print("3. Both files are searchable via execute_query regardless of type")
    print(DIVIDER)
    answer, _ = await us.async_execute_query(
        "What experience does Alice have?", database="alice",
        optional_properties={"output_form": "nl", "max_interaction_rounds": 0},
    )
    print("  Answer:", answer)

    shutil.rmtree(tmp)
    print()
    print("Demo complete.")


asyncio.run(main())
