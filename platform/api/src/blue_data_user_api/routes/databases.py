from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from blue_data_user_api.auth import require_api_key
from blue_data_user_api.source import _default_user_props

# The name becomes a directory and file name under the data directory, so it
# must not be able to climb out of it ("..") or nest (".", "/").
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

router = APIRouter(prefix="/databases", tags=["databases"], dependencies=[Depends(require_api_key)])


class CreateDatabaseRequest(BaseModel):
    """No fields: every store goes under ``BLUE_DATA_USER_SOURCE_DATA_DIR/sources/{name}/``.

    Callers used to be able to pass a ``_class`` and a ``connection`` for each
    store, which let any REST caller make the server import a class of their
    choosing and later delete files anywhere it could write (#134). Unknown
    keys are rejected so such a request fails loudly instead of being ignored.
    """

    model_config = ConfigDict(extra="forbid")


@router.get("", summary="List users")
async def list_databases(request: Request) -> list[str]:
    return request.app.state.source.list_users()


@router.post("/{name}", status_code=status.HTTP_201_CREATED, summary="Create user")
async def create_database(name: str, request: Request, body: CreateDatabaseRequest | None = None) -> dict:
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Database name must be 1-64 letters, digits, '_' or '-', starting with a letter or digit",
        )
    props = _default_user_props(name, request.app.state.data_dir)
    await request.app.state.source.create_user(
        name,
        registry_props=props["registry"],
        kb_source_props=props["kb_source"],
        metadata_source_props=props["metadata_source"],
        contact_source_props=props["contact_source"],
        session_source_props=props["session_source"],
        doc_source_props=props["doc_source"],
        # Onboarding is an interview; a REST call has nobody to interview.
        onboard=False,
        onboard_metadata=False,
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
