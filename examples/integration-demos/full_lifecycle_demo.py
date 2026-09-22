"""
Full lifecycle -- create, seed, extract, query, converse, observe, in one flow.

The direct blue-data-user-source analog of the sibling blue-data-kb-source
repo's own integration-demos hero script: not a new backend (that's
backends/) and not a new external framework (that's framework-demos/), but
the stages backends/ and feature-demos/ each show in isolation, chained into
one continuous narrative on one small, realistic user --

    create user -> seed metadata & a contact method -> extract a source doc
    into the KB -> run a session of natural-language queries -> inspect the
    session record -> end the session

Requires OPENAI_API_KEY (extraction and query rewriting/expansion/assessment/
synthesis all call the LLM).

Run:
    python3 examples/integration-demos/full_lifecycle_demo.py
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
Carol Diaz is a principal data scientist at Nimbus Analytics, based in
Austin, Texas. She has led the company's recommendation-systems team since
2022 and previously worked as a machine learning engineer at a logistics
startup. Carol prefers to be contacted by email for anything non-urgent.
"""


async def main() -> None:
    print(DIVIDER)
    print("1. Create a user (all-in-memory: registry, KB, metadata, contacts, sessions)")
    print(DIVIDER)

    us = MemoryUserSource("full-lifecycle-demo")
    await us.create_user(
        "carol",
        registry_props=_MEM_JSON,
        kb_source_props=_MEM_KB,
        metadata_source_props=_MEM_JSON,
        contact_source_props=_MEM_JSON,
        session_source_props=_MEM_JSON,
    )
    print(f"Users: {us.list_users()}")

    print()
    print(DIVIDER)
    print("2. Seed metadata and register a contact method")
    print(DIVIDER)

    us.set_metadata("carol", "identity.name", "Carol")
    us.set_metadata("carol", "identity.timezone", "America/Chicago")
    us.set_metadata("carol", "preferences.verbosity", "brief")
    us.set_metadata("carol", "availability.preferred_channel", "email")
    us.set_metadata("carol", "privacy.consent_level", "standard")
    await us.add_contact_method(
        "carol", "email", "work",
        {"inbound_provider": "stdio", "address": "carol@example.com"},
        preference=0,
    )
    print("Metadata set: identity.name, identity.timezone, preferences.verbosity, "
          "availability.preferred_channel, privacy.consent_level")
    print(f"Metadata snapshot: {us.list_metadata('carol')}")

    print()
    print(DIVIDER)
    print("3. add_source -- extract structured data from a bio into the KB")
    print(DIVIDER)

    with tempfile.TemporaryDirectory(prefix="blue-userdb-full-lifecycle-demo-") as tmp:
        bio_path = Path(tmp) / "carol-bio.txt"
        bio_path.write_text(BIO)
        await us.add_source(
            str(bio_path), database="carol",
            optional_properties={
                "queries": [
                    "Extract Carol's job title and employer.",
                    "Extract Carol's location and work history.",
                ]
            },
        )

    data_entries = await us.list_data("carol")
    source_entries = await us.list_sources("carol")
    print(f"list_data('carol') -> {len(data_entries)} row(s)")
    print(f"list_sources('carol') -> {len(source_entries)} source(s): "
          f"{[s.get('name') for s in source_entries]}")

    print()
    print(DIVIDER)
    print("4. Run a session of two queries")
    print(DIVIDER)

    session_id = await us.create_session("carol")
    print(f"Created session {session_id}")

    answer1, session_id = await us.async_execute_query(
        "What is Carol's job title and where does she work?",
        database="carol",
        optional_properties={
            # max_interaction_rounds=1: FreshnessMetric fails whenever the KB
            # answer-agent doesn't happen to call get_metadata for a lookup (no
            # modified/created timestamp ends up in query_results_metadata), and
            # then never recovers regardless of what the user says -- capped here
            # to keep this walkthrough's output focused. See the freshness gotcha
            # in scenario-demos/interactive_clarification_demo.py for the full story.
            "output_form": "nl", "session": session_id, "max_interaction_rounds": 1,
        },
    )
    print(f"\nQ: What is Carol's job title and where does she work?\nA: {answer1}")

    answer2, session_id = await us.async_execute_query(
        "Where is Carol based?",
        database="carol",
        optional_properties={
            # max_interaction_rounds=1: FreshnessMetric fails whenever the KB
            # answer-agent doesn't happen to call get_metadata for a lookup (no
            # modified/created timestamp ends up in query_results_metadata), and
            # then never recovers regardless of what the user says -- capped here
            # to keep this walkthrough's output focused. See the freshness gotcha
            # in scenario-demos/interactive_clarification_demo.py for the full story.
            "output_form": "nl", "session": session_id, "max_interaction_rounds": 1,
        },
    )
    print(f"\nQ: Where is Carol based?\nA: {answer2}")

    print()
    print(DIVIDER)
    print("5. Inspect the session record, then end it")
    print(DIVIDER)

    session = await us.get_session("carol", session_id)
    print(f"Session {session_id} has {len(session.get('queries', {}))} quer(y/ies), "
          f"status={session.get('status')}")

    await us.end_session("carol", session_id)
    ended_session = await us.get_session("carol", session_id)
    print(f"After end_session: status={ended_session.get('status')}")

    all_sessions = await us.list_sessions("carol")
    print(f"list_sessions('carol') -> {len(all_sessions)} session(s) total")

    print()
    print("Demo complete.")


asyncio.run(main())
