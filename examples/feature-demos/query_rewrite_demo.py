"""
Query rewriting -- contextualize_query's name substitution, expand_query's
schema-grounded sub-questions.

contextualize_query rewrites a query so every self-reference to the user
("you", "your", "the user", pronouns, the user's own name) becomes the user's
actual name -- unambiguous once it reaches sub-question generation and metric
evaluation. expand_query then decomposes the rewritten query into standalone,
third-person sub-questions grounded in what the KB schema can actually answer,
scaling the count to the query's complexity (zero for an already-specific
lookup, up to 5 for a broad one).

Run from examples/feature-demos/:
    python3 query_rewrite_demo.py
"""
import asyncio
from pathlib import Path

from blue_data_user_source import MemoryUserSource
from blue_data_user_source.data.manager import CLS_JSON_MEMORY, CLS_KB_MEMORY, UserDataManager
from blue_data_user_source.reasoning import UserQueryReasoner

DIVIDER = "-" * 60
_DATA_DIR = Path(__file__).parent.parent.parent / "lib" / "src" / "blue_data_user_source" / "data"
_MEM_JSON = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}


async def main():
    # MemoryUserSource is the UserSource callers actually hold; the reasoner
    # separately needs a built UserDataManager, so build one directly against
    # the same schema (the pattern lib/tests/conftest.py uses to test the
    # reasoner in isolation).
    us = MemoryUserSource("query-rewrite-demo")
    manager = UserDataManager("alice", _MEM_JSON)
    await manager.build(
        schema_path=str(_DATA_DIR / "schema.json"),
        kb_source_props=_MEM_KB,
        metadata_schema_path=str(_DATA_DIR / "metadata_schema.json"),
        metadata_source_props=_MEM_JSON,
        contact_schema_path=str(_DATA_DIR / "contact_schema.json"),
        contact_source_props=_MEM_JSON,
        session_source_props=_MEM_JSON,
    )
    manager.set_metadata("identity.name", "Alice")
    reasoner = UserQueryReasoner(source=us, manager=manager)

    print(DIVIDER)
    print("1. contextualize_query -- self-references become the user's name")
    print(DIVIDER)
    for query in ("what is your age", "What is the user's age?", "you like remote work?"):
        rewritten = await reasoner.contextualize_query(query)
        print(f"  {query!r:38} -> {rewritten!r}")

    print()
    print(DIVIDER)
    print("2. expand_query -- a broad query, grounded in the real KB schema")
    print(DIVIDER)
    broad = "What jobs is Alice suitable for?"
    questions = await reasoner.expand_query(broad)
    print(f"Query: {broad!r}")
    for q in questions:
        print(f"  - {q}")
    print(f"({len(questions)} sub-question(s) -- each targets a distinct schema facet)")

    print()
    print(DIVIDER)
    print("3. expand_query -- a narrow, already-specific lookup")
    print(DIVIDER)
    specific = "What is Alice's timezone?"
    questions = await reasoner.expand_query(specific)
    print(f"Query: {specific!r}")
    print(f"Sub-questions: {questions}")
    print(f"({len(questions)} -- the model may return zero here, since the "
          "original query is already a single specific lookup; it isn't required to)")


asyncio.run(main())
