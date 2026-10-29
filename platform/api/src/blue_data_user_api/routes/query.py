from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from blue_data_user_api.auth import SECURITY

router = APIRouter(tags=["query"], dependencies=SECURITY)


class QueryRequest(BaseModel):
    query: str
    output_form: str = "json"
    session: str | None = None
    include_expanded: bool = False
    # Bounds on the query's LLM calls (#178); unset, the library's defaults.
    max_subqueries: int | None = Field(
        default=None, ge=0,
        description="Most sub-questions added to the query, each answered by the KB's agent; "
                    "0 answers the query alone (default: as many as needed, at most 5).",
    )
    max_kb_turns: int | None = Field(
        default=None, ge=1, description="Most tool-calling turns of the KB's agent per sub-question (default 25).",
    )
    max_interaction_rounds: int | None = Field(
        default=None, ge=0, description="Most rounds of clarification questions to the user (default 3).",
    )


@router.post("/{name}/query", summary="Query user data")
async def query_database(name: str, body: QueryRequest, request: Request) -> dict:
    optional: dict = {"output_form": body.output_form}
    if body.session:
        optional["session"] = body.session
    if body.include_expanded:
        optional["include_expanded"] = True
    for key in ("max_subqueries", "max_kb_turns", "max_interaction_rounds"):
        if getattr(body, key) is not None:
            optional[key] = getattr(body, key)
    result, session_id = await request.app.state.source.async_execute_query(
        body.query, database=name, optional_properties=optional
    )
    return {"database": name, "query": body.query, "results": result, "session_id": session_id}
