from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from blue_data_user_api.auth import require_api_key

router = APIRouter(tags=["metadata"], dependencies=[Depends(require_api_key)])


class MetadataSetRequest(BaseModel):
    value: Any


@router.get("/{name}/metadata", summary="List all metadata")
async def list_metadata(name: str, request: Request) -> dict:
    data = request.app.state.source.list_metadata(name)
    return {"database": name, "metadata": data}


@router.get("/{name}/metadata/{key:path}", summary="Get a metadata key")
async def get_metadata(name: str, key: str, request: Request) -> dict:
    value = request.app.state.source.get_metadata(name, key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Metadata key {key!r} not found")
    return {"database": name, "key": key, "value": value}


@router.put("/{name}/metadata/{key:path}", summary="Set a metadata key")
async def set_metadata(name: str, key: str, body: MetadataSetRequest, request: Request) -> dict:
    request.app.state.source.set_metadata(name, key, body.value)
    return {"database": name, "key": key, "value": body.value}


@router.delete("/{name}/metadata/{key:path}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a metadata key")
async def delete_metadata(name: str, key: str, request: Request) -> None:
    request.app.state.source.delete_metadata(name, key)
