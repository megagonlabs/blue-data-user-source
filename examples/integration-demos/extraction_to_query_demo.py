"""
Extraction feeds querying -- add_source(queries=...) populates a user's
knowledge base, then execute_query queries the result.

The feature-demos/ scripts that exercise querying each hand-build the data
they query rather than extracting it from text first. This demo chains the
two features UserSource actually exists to combine: write-side LLM extraction
(add_source's Type 2 ingestion, see design/04-detailed-architecture.md) and
read-side natural language querying (execute_query's contextualize/expand/
assess pipeline), against the same user -- so the KB that gets queried is
exactly what a real "register a document, then ask questions about it"
workflow would produce.

Requires OPENAI_API_KEY (extraction and query rewriting/expansion/synthesis
all call the LLM).

Run:
    python3 examples/integration-demos/extraction_to_query_demo.py
"""
import asyncio
import tempfile
from pathlib import Path

from blue_data_user_source import MemoryUserSource
from blue_data_user_source.data.manager import CLS_JSON_MEMORY, CLS_KB_MEMORY

DIVIDER = "-" * 60

_MEM_JSON = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}

BIO = """\
Bob Chen is a data scientist at Nimbus Analytics, where he has worked since
2021. He specializes in natural language processing and has published two
papers on retrieval-augmented generation. Before Nimbus, Bob was a research
assistant at Carnegie Mellon University. He is proficient in Python, PyTorch,
and SQL, and is currently based in Pittsburgh, Pennsylvania.
"""


async def main() -> None:
    print(DIVIDER)
    print("1. Create a user with an empty knowledge base")
    print(DIVIDER)

    us = MemoryUserSource("extraction-to-query-demo")
    await us.create_user(
        "bob",
        registry_props=_MEM_JSON,
        kb_source_props=_MEM_KB,
        metadata_source_props=_MEM_JSON,
        contact_source_props=_MEM_JSON,
        session_source_props=_MEM_JSON,
        # These demos are non-interactive: create_user onboards by default,
        # which would prompt on stdin and make the captured output unreproducible.
        onboard=False,
        onboard_metadata=False,
    )
    us.set_metadata("bob", "identity.name", "Bob")
    print("Created user 'bob'")

    print()
    print(DIVIDER)
    print("2. add_source(queries=...) -- extract structured data from a bio into the KB")
    print(DIVIDER)

    with tempfile.TemporaryDirectory(prefix="blue-userdb-extraction-to-query-demo-") as tmp:
        bio_path = Path(tmp) / "bob-bio.txt"
        bio_path.write_text(BIO)
        await us.add_source(
            str(bio_path), database="bob",
            optional_properties={
                "queries": [
                    "Extract Bob's job title, employer, and skills.",
                    "Extract Bob's education and work history.",
                ]
            },
        )

    entries = await us.list_data("bob")
    print(f"list_data('bob') -> {len(entries)} row(s) extracted from one bio paragraph")

    print()
    print(DIVIDER)
    print("3. execute_query -- query the KB that add_source just built")
    print(DIVIDER)

    for query in [
        "What are Bob's technical skills?",
        "Where does Bob currently work and what does he specialize in?",
    ]:
        answer, session_id = await us.async_execute_query(
            query, database="bob", optional_properties={"output_form": "nl"},
        )
        print(f"\nQ: {query}")
        print(f"A: {answer}")

    print()
    print("Demo complete.")


asyncio.run(main())
