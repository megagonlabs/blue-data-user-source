"""
LangGraph + blue-data-user-source: direct Python API integration.

A small LangGraph pipeline built directly on UserSource's own read primitive
-- execute_query_nl -- rather than through the MCP server (that's
langgraph_mcp_demo.py). Contrast the two: there, a ReAct agent freely
discovers and chooses among ALL of blue-data-user-mcp's tools
(create_database, add_source, set_metadata, add_contact, query, ...); here,
the graph has exactly one fixed capability (answer one question about a user
that already exists) and an LLM only decides how to *phrase* the lookup and
the final response, not which tool to call.

Unlike the sibling blue-data-kb-source repo's own langgraph_direct_demo.py,
which builds a 3-node pipeline around KBSource's low-level read primitives
(search_data, get_metadata) specifically to avoid its answer() black box,
UserSource has no lower-level public read primitive than execute_query /
execute_query_nl -- that already IS the "direct API" here. Query rewriting,
sub-question expansion, quality assessment, and live user clarification (see
design/04-detailed-architecture.md and ADR-022 in design/13-decision-log.md)
all happen inside that one call, invisibly to this pipeline:

    lookup  ->  respond

    1. lookup   -- UserSource.execute_query_nl(), UserSource's one real read
                   primitive
    2. respond  -- an LLM call turns the lookup's answer into a message for
                   the caller's actual task

Requires OPENAI_API_KEY.

Run:
    pip install langgraph langchain-openai
    python3 examples/framework-demos/langgraph_direct_demo.py
"""
import asyncio
import tempfile
from pathlib import Path
from typing import TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from blue_data_user_source import MemoryUserSource
from blue_data_user_source.data.manager import CLS_JSON_MEMORY, CLS_KB_MEMORY

DIVIDER = "-" * 60
_MEM_JSON = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}

BIO = """\
Alice Johnson is a senior software engineer at IBM, where she has worked
since 2019. She specializes in distributed systems and prefers async written
updates over live calls whenever possible.
"""

us = MemoryUserSource("direct-demo")
model: ChatOpenAI | None = None  # constructed in main(), after the user is seeded


class State(TypedDict):
    task: str      # the caller's actual task, in their own words
    question: str  # the question to put to Alice's data store
    lookup: str    # execute_query_nl's synthesized answer
    reply: str     # final drafted message


# --------------------------------------------------------------------------- #
# Node 1: lookup -- UserSource.execute_query_nl(), no custom pipeline needed
# --------------------------------------------------------------------------- #

def lookup(state: State) -> dict:
    # The DataSource form returns list[dict] rows; an "nl" answer is one
    # {"answer": ...} row (#164).
    [row] = us.execute_query_nl(
        state["question"], database="alice",
        # max_interaction_rounds=1: FreshnessMetric fails whenever the KB
        # answer-agent doesn't call get_metadata for a lookup and never
        # recovers -- see the gotcha documented in
        # scenario-demos/interactive_clarification_demo.py. Capped here to
        # keep this pipeline's output focused on the LangGraph wiring.
        optional_properties={"output_form": "nl", "max_interaction_rounds": 1},
    )
    answer = row["answer"]
    print(f"[lookup] execute_query_nl({state['question']!r}) -> {answer!r}")
    return {"lookup": answer}


# --------------------------------------------------------------------------- #
# Node 2: respond -- LLM turns the lookup result into a drafted message
# --------------------------------------------------------------------------- #

def respond(state: State) -> dict:
    prompt = (
        f"Task: {state['task']}\n\n"
        f"What we know about Alice: {state['lookup']}\n\n"
        "Draft a short message that accomplishes the task, respecting anything "
        "we know about Alice's stated preferences."
    )
    reply = model.invoke(prompt).content
    print(f"[respond] {reply}")
    return {"reply": reply}


# --------------------------------------------------------------------------- #
# Build the graph: lookup -> respond -> END
# --------------------------------------------------------------------------- #

graph = StateGraph(State)
graph.add_node("lookup", lookup)
graph.add_node("respond", respond)
graph.set_entry_point("lookup")
graph.add_edge("lookup", "respond")
graph.add_edge("respond", END)
agent = graph.compile()


async def seed() -> None:
    await us.create_user(
        "alice",
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
    us.set_metadata("alice", "identity.name", "Alice")
    with tempfile.TemporaryDirectory(prefix="blue-userdb-langgraph-direct-demo-") as tmp:
        bio_path = Path(tmp) / "alice-bio.txt"
        bio_path.write_text(BIO)
        await us.add_source(
            str(bio_path), database="alice",
            optional_properties={
                "queries": ["Extract Alice's job title, employer, and communication preferences."]
            },
        )


def main() -> None:
    global model

    print(DIVIDER)
    print("1. Seed Alice's profile")
    print(DIVIDER)
    asyncio.run(seed())
    print("Seeded job title, employer, and communication preferences")

    print()
    print(DIVIDER)
    print("2. Run the lookup -> respond pipeline")
    print(DIVIDER)

    model = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    task = "Ask Alice for 30 minutes next week to discuss the migration project."
    question = "What does Alice do and how does she prefer to be contacted?"
    print(f"Task: {task}")
    print(f"Question put to Alice's data store: {question}\n")

    result = agent.invoke({"task": task, "question": question, "lookup": "", "reply": ""})

    print()
    print("Final drafted message:")
    print(result["reply"])
    print()
    print("Demo complete.")


main()
