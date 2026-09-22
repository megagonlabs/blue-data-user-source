"""
Scenario: resolving missing data through interactive clarification.

Problem: a query can need information a user's data store simply doesn't have
yet. Returning an incomplete answer -- or silently guessing -- would be
wrong. Most systems either fail the query outright or hand back a partial
answer with no indication anything is missing.

Solution: execute_query's completeness check (see design/04-detailed-architecture.md
and design/13-decision-log.md ADR-022) evaluates the aggregated result against
CompletenessMetric, and if it fails, asks the user directly through their
preferred contact method before giving up -- then re-checks. The caller never
has to notice: this all happens inside one execute_query call.

This demo seeds a user's knowledge base with a partial profile (job title,
years of experience -- nothing about compensation), then asks a question that
needs the missing piece. Nothing here is scripted around a fake evaluation;
CompletenessMetric's score comes from a real OpenAI call, so the interaction
only fires if the model genuinely judges the KB lookup incomplete.

Requires OPENAI_API_KEY (query rewriting/expansion/completeness assessment/
synthesis all call the LLM).

Non-interactive stdin: the registered contact method is protocol="stdio",
whose real handler (ContactMethod._stdio_manager in
lib/src/blue_data_user_source/interaction/contact.py) just does
`sys.stdin.readline()` when it needs a reply. To let this run unattended, we
monkeypatch sys.stdin to a StringIO holding Alice's scripted reply for the
duration of the query -- the real stdio handler code path still runs
end-to-end, it just isn't blocked on a real terminal.

Run:
    python3 examples/scenario-demos/interactive_clarification_demo.py
"""
import asyncio
import io
import json
import sys
import tempfile
from pathlib import Path

from blue_data_user_source import MemoryUserSource
from blue_data_user_source.data.manager import CLS_JSON_MEMORY, CLS_KB_MEMORY

DIVIDER = "=" * 60
STEP = "-" * 60

_MEM_JSON = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}

BIO = (
    "Alice is a senior software engineer with 8 years of experience in "
    "distributed systems. She has led two major platform migrations and "
    "mentors junior engineers on her team."
)
QUERY = "What salary range and notice period should a recruiter expect for Alice?"
ALICE_REPLY = (
    "I'm looking for $150,000-$170,000 base plus standard equity, and I'd need "
    "to give my current employer 4 weeks notice."
)


async def main() -> None:
    print(DIVIDER)
    print("Scenario: resolving missing data through interactive clarification")
    print(DIVIDER)
    print()
    print("Problem:  a query needs information the user's data store doesn't have yet.")
    print("          Returning an incomplete answer, or guessing, would be wrong.")
    print("Solution: execute_query's completeness check asks the user directly through")
    print("          their preferred contact method, then re-checks -- see ADR-022.")

    print()
    print(STEP)
    print("Step 1 -- create Alice's user database with a partial profile")
    print(STEP)

    us = MemoryUserSource("clarification-demo")
    await us.create_user(
        "alice",
        registry_props=_MEM_JSON,
        kb_source_props=_MEM_KB,
        metadata_source_props=_MEM_JSON,
        contact_source_props=_MEM_JSON,
        session_source_props=_MEM_JSON,
    )
    us.set_metadata("alice", "identity.name", "Alice")

    with tempfile.TemporaryDirectory(prefix="blue-userdb-clarification-demo-") as tmp:
        bio_path = Path(tmp) / "alice-bio.txt"
        bio_path.write_text(BIO)
        await us.add_source(
            str(bio_path), database="alice",
            optional_properties={"queries": ["What is Alice's job title and years of experience?"]},
        )
    print("Seeded Alice's profile: job title, years of experience -- nothing about compensation")

    print()
    print(STEP)
    print("Step 2 -- register Alice's contact method (stdio, for this demo)")
    print(STEP)
    await us.add_contact_method("alice", "stdio", "default", {})
    print("Registered a stdio contact method")

    print()
    print(STEP)
    print(f"Step 3 -- run the query: {QUERY!r}")
    print(STEP)
    print("(the KB has nothing about salary or notice period, so the completeness check")
    print("is expected to fail and trigger a clarifying question over stdio)")

    # Feed Alice's scripted reply through stdin so the real stdio contact handler
    # (sys.stdin.readline() in ContactMethod._stdio_manager) has something to read
    # without blocking on a real terminal. The interaction still runs for real --
    # this only replaces the human at the keyboard.
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(ALICE_REPLY + "\n")
    try:
        # max_interaction_rounds=1: FreshnessMetric (the other default metric run
        # alongside CompletenessMetric) scores purely off `modified`/`created`
        # timestamps in query_results_metadata -- and the KB answer-agent only
        # populates those when it happens to call get_metadata for a given
        # lookup, which it doesn't always do. When it doesn't, freshness scores
        # 0.0 and never recovers no matter what the user says, so raising
        # max_rounds here would just consume repeated empty stdin reads once
        # completeness is already satisfied. This is real, current system
        # behavior (see examples/README.md), not something this demo hides.
        answer, session_id = await us.async_execute_query(
            QUERY, database="alice",
            optional_properties={
                "output_form": "nl", "include_expanded": True, "max_interaction_rounds": 1,
            },
        )
    finally:
        sys.stdin = real_stdin

    print()
    print(DIVIDER)
    print("Result")
    print(DIVIDER)
    print(f"Session: {session_id}")
    print()
    print("Synthesized answer:")
    print(answer["result"])
    print()
    print("Expanded (per-sub-question) results -- look for the query answered by Alice herself:")
    print(answer["expanded"])

    session = await us.get_session("alice", session_id)
    interactions = [
        i
        for q in session.get("queries", {}).values()
        for i in q.get("interactions", {}).values()
    ]
    print()
    print(f"Session record shows {len(interactions)} interaction(s) over this query:")
    for i in interactions:
        contact = i.get("contact") or {}
        print(f"  channel={contact.get('protocol')}/{contact.get('name')} "
              f"question={i.get('question')!r} response={i.get('response')!r}")

    print()
    if interactions:
        print("The completeness check failed on the first pass, Alice was asked directly,")
        print("and her answer resolved it -- the caller only ever made one execute_query call.")
        print()
        print("Gotcha: FreshnessMetric (evaluated alongside CompletenessMetric on every round)")
        print("still fails even after Alice answers -- it scores off `modified`/`created`")
        print("timestamps that only show up in query_results_metadata when the KB answer-agent")
        print("happens to call get_metadata for that lookup, which it doesn't always do. With no")
        print("timestamps at all, freshness scores 0.0 and can never pass, regardless of what the")
        print("user says. In a real deployment with max_interaction_rounds > 1 this can burn every")
        print("remaining round on an unresolvable metric even after the metric that actually")
        print("needed the user's input has already passed.")
    else:
        print("No clarification was needed this run -- the model judged the initial lookup")
        print("complete enough on its own (LLM-scored, so this can vary run to run).")

    print()
    print("Demo complete.")


asyncio.run(main())
