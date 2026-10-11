from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from blue_data_user_api.auth import require_api_key
from blue_data_user_source import QueryError

router = APIRouter(tags=["data"], dependencies=[Depends(require_api_key)])


class AddSourceRequest(BaseModel):
    # The source's text. Never read as a path: that let any caller have the
    # server ingest, and then return, any file it could read (#133).
    source: str = Field(min_length=1)
    name: str | None = None
    description: str | None = None
    original: str | None = None
    queries: list[str] | None = None


@router.get("/{name}/data", summary="List ingested data entries")
async def list_data(name: str, request: Request) -> dict:
    entries = await request.app.state.source.list_data(name)
    return {"database": name, "data": entries}


@router.get("/{name}/sources", summary="List registered sources")
async def list_sources(name: str, source_id: str | None = None, request: Request = None) -> dict:
    entries = await request.app.state.source.list_sources(name, source_id)
    return {"database": name, "sources": entries}


@router.post("/{name}/sources", status_code=status.HTTP_201_CREATED, summary="Add a source from text")
async def add_source(name: str, body: AddSourceRequest, request: Request) -> dict:
    """Add `source` as a text document. Text only: file uploads are not supported over REST in 1.0."""
    props: dict[str, Any] = {}
    if body.name:
        props["name"] = body.name
    if body.description:
        props["description"] = body.description
    if body.original:
        props["original"] = body.original
    if body.queries:
        props["queries"] = body.queries
    props.setdefault("name", "text")
    # Ingested as text: no server path is read (#133), and none is written or
    # recorded as the source's location (#151).
    props["location"] = f"rest:{props['name']}"
    await request.app.state.source.add_text_source(body.source, database=name, optional_properties=props)
    return {"database": name, "added": True}


@router.delete("/{name}/sources/{source_name}", summary="Remove a source")
async def remove_source(name: str, source_name: str, request: Request) -> dict:
    """Remove a source by name or id; facts extracted from it are kept."""
    try:
        removed = await request.app.state.source.remove_source(name, source_name)
    except QueryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return {"database": name, **removed}
