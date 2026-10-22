from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from blue_data_user_api.auth import SECURITY

router = APIRouter(tags=["query"], dependencies=SECURITY)


class QueryRequest(BaseModel):
    query: str
    output_form: str = "json"
    session: str | None = None
    include_expanded: bool = False


@router.post("/{name}/query", summary="Query user data")
async def query_database(name: str, body: QueryRequest, request: Request) -> dict:
    optional: dict = {"output_form": body.output_form}
    if body.session:
        optional["session"] = body.session
    if body.include_expanded:
        optional["include_expanded"] = True
    result, session_id = await request.app.state.source.async_execute_query(
        body.query, database=name, optional_properties=optional
    )
    return {"database": name, "query": body.query, "results": result, "session_id": session_id}
