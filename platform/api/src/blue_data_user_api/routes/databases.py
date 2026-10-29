from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from blue_data_user_api.auth import SECURITY
from blue_data_user_source import QueryError, validate_user_name
from blue_data_user_source.data.manager import NEW_USER_DOC_SOURCE_PROPS, resolve_doc_search

router = APIRouter(prefix="/databases", tags=["databases"], dependencies=SECURITY)


class CreateDatabaseRequest(BaseModel):
    """How the user's documents are searched; every store goes under
    ``BLUE_DATA_USER_SOURCE_DATA_DIR/sources/{name}/``.

    Callers used to be able to pass a ``_class`` and a ``connection`` for each
    store, which let any REST caller make the server import a class of their
    choosing and later delete files anywhere it could write (#134). Only named
    values are accepted (#173), and unknown keys are rejected so such a request
    fails loudly instead of being ignored.
    """

    model_config = ConfigDict(extra="forbid")

    doc_search_mode: Literal["vector", "hybrid", "bm25"] | None = Field(
        default=None,
        description="How the user's documents are searched: 'vector' (by meaning; the default), "
                    "'hybrid' (meaning and keywords) or 'bm25' (keywords; its index lasts only "
                    "for the server process that added the documents).",
    )
    doc_embedding_model: Literal["openai", "dummy"] | None = Field(
        default=None,
        description="'openai' (the default; needs OPENAI_API_KEY) or 'dummy' "
                    "(a hash, no API calls; only with doc_search_mode 'bm25').",
    )


@router.get("", summary="List users")
async def list_databases(request: Request) -> list[str]:
    return request.app.state.source.list_users()


@router.post("/{name}", status_code=status.HTTP_201_CREATED, summary="Create user")
async def create_database(name: str, request: Request, body: CreateDatabaseRequest | None = None) -> dict:
    # Checked before the defaults are built from it: the name becomes paths (#134).
    try:
        validate_user_name(name)
    except QueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    props = request.app.state.source.default_user_props(name)
    body = body or CreateDatabaseRequest()
    # A QueryError here (vector or hybrid over 'dummy') is answered 422.
    doc_source = resolve_doc_search(
        props.get("doc_source") or NEW_USER_DOC_SOURCE_PROPS,
        search_mode=body.doc_search_mode, embedding_model=body.doc_embedding_model,
    )
    await request.app.state.source.create_user(
        name,
        registry_props=props["registry"],
        kb_source_props=props["kb_source"],
        metadata_source_props=props["metadata_source"],
        contact_source_props=props["contact_source"],
        session_source_props=props["session_source"],
        doc_source_props=doc_source,
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
    kept = await request.app.state.source.reset_user(name)
    # Recorded paths outside the data directory are never deleted (#156); a DELETE
    # (204, no body) only logs them.
    return {"name": name, "reset": True, **({"not_deleted": kept} if kept else {})}
