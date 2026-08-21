from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from blue_data_user_api.auth import require_api_key
from blue_data_user_api.source import _default_user_props

router = APIRouter(prefix="/databases", tags=["databases"], dependencies=[Depends(require_api_key)])


class CreateDatabaseRequest(BaseModel):
    registry: dict[str, Any] | None = None
    kb_source: dict[str, Any] | None = None
    metadata_source: dict[str, Any] | None = None
    contact_source: dict[str, Any] | None = None
    session_source: dict[str, Any] | None = None
    doc_source: dict[str, Any] | None = None


@router.get("", summary="List users")
async def list_databases(request: Request) -> list[str]:
    return request.app.state.source.list_users()


@router.post("/{name}", status_code=status.HTTP_201_CREATED, summary="Create user")
async def create_database(name: str, body: CreateDatabaseRequest, request: Request) -> dict:
    source = request.app.state.source
    data_dir = request.app.state.data_dir
    defaults = _default_user_props(name, data_dir)
    props: dict[str, Any] = {
        "registry": body.registry or defaults["registry"],
        "kb_source": body.kb_source or defaults["kb_source"],
        "metadata_source": body.metadata_source or defaults["metadata_source"],
        "contact_source": body.contact_source or defaults["contact_source"],
        "session_source": body.session_source or defaults["session_source"],
        "doc_source": body.doc_source or defaults["doc_source"],
    }
    await source.create_user(
        name,
        registry_props=props["registry"],
        kb_source_props=props["kb_source"],
        metadata_source_props=props["metadata_source"],
        contact_source_props=props["contact_source"],
        session_source_props=props["session_source"],
        doc_source_props=props["doc_source"],
    )
    return {"name": name}


@router.get("/{name}", summary="Get user info")
async def get_database(name: str, request: Request) -> dict:
    info = request.app.state.source.get_user(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"User {name!r} not found")
    return {"name": name, **info}


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete user")
async def delete_database(name: str, request: Request) -> None:
    await request.app.state.source.delete_user(name)


@router.post("/{name}/reset", summary="Reset user data")
async def reset_database(name: str, request: Request) -> dict:
    await request.app.state.source.reset_user(name)
    return {"name": name, "reset": True}
