"""
LangGraph + blue-data-user-source: MCP-based integration.

A ReAct agent that uses the real blue-data-user-mcp server as tools via
langchain-mcp-adapters. No UserSource-specific code on the LangGraph side at
all -- the agent discovers every tool the running MCP server exposes
(create_database, add_source, query, set_metadata, list_metadata,
add_contact, ...) and picks which ones to call itself, in whatever order the
task requires.

Contrast with langgraph_direct_demo.py, which hand-builds a fixed 2-node
pipeline around UserSource.execute_query_nl -- the only thing that pipeline
can ever do is answer one question about a user that already exists. Here,
the agent can also create the user and set metadata, entirely through tool
calls it chooses itself; there is no fixed pipeline at all.

Run:
    pip install langgraph langchain-openai langchain-mcp-adapters
    pip install -e platform/mcp/
    python3 examples/framework-demos/langgraph_mcp_demo.py

The blue-data-user-mcp server (the `udb-mcp` console script installed by
platform/mcp/) is launched automatically as a subprocess (stdio transport),
pointed at a scratch directory via BLUE_DATA_USER_SOURCE_DATA_DIR so it never
touches the default ~/.udb.
"""
import asyncio
import os
import shutil
import tempfile

from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent


async def main() -> None:
    tmp = tempfile.mkdtemp(prefix="blue-data-user-mcp-demo-")
    print(f"Scratch data directory: {tmp}\n")

    model = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    # Launch blue-data-user-mcp (the udb-mcp console script) as a subprocess,
    # pointed at the scratch directory.
    client = MultiServerMCPClient({
        "udb": {
            "command": "udb-mcp",
            "args": [],
            "transport": "stdio",
            "env": {**os.environ, "BLUE_DATA_USER_SOURCE_DATA_DIR": tmp},
        }
    })

    tools = await client.get_tools()
    print(f"Loaded {len(tools)} tools from blue-data-user-mcp: {[t.name for t in tools]}\n")

    agent = create_react_agent(model, tools)

    queries = [
        "Create a user database named 'dana'.",
        "Set dana's identity.name metadata to 'Dana' and preferences.verbosity to 'brief'.",
        "List all the metadata currently stored for dana.",
    ]

    try:
        for query in queries:
            print(f"Query: {query}")
            result = await agent.ainvoke({
                "messages": [{"role": "user", "content": query}]
            })
            answer = result["messages"][-1].content
            print(f"Answer: {answer}\n")
    finally:
        shutil.rmtree(tmp)
        print(f"Cleaned up {tmp}")


if __name__ == "__main__":
    asyncio.run(main())
