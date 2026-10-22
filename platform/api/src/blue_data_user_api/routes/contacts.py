from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, status
from pydantic import BaseModel

from blue_data_user_api.auth import SECURITY

router = APIRouter(tags=["contacts"], dependencies=SECURITY)


class ContactRequest(BaseModel):
    protocol: str
    name: str
    details: dict[str, Any]
    preference: int = 0


class ContactUpdateRequest(BaseModel):
    details: dict[str, Any] | None = None
    preference: int | None = None


@router.get("/{name}/contacts", summary="List contact methods")
async def list_contacts(name: str, protocol: str | None = None, request: Request = None) -> dict:
    methods = await request.app.state.source.list_contact_methods(name, protocol)
    return {"database": name, "contacts": [m.public_dict() for m in methods]}  # secrets masked (#143)


@router.post("/{name}/contacts", status_code=status.HTTP_201_CREATED, summary="Add contact method")
async def add_contact(name: str, body: ContactRequest, request: Request) -> dict:
    await request.app.state.source.add_contact_method(
        name, body.protocol, body.name, body.details, body.preference
    )
    return {"database": name, "protocol": body.protocol, "name": body.name}


@router.get("/{name}/contacts/{protocol}/{contact_name}", summary="Get contact method")
async def get_contact(name: str, protocol: str, contact_name: str, request: Request) -> dict:
    method = await request.app.state.source.get_contact_method(name, protocol, contact_name)
    if method is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Contact {protocol}/{contact_name!r} not found")
    return {"database": name, **method.public_dict()}


@router.patch("/{name}/contacts/{protocol}/{contact_name}", summary="Update contact method")
async def update_contact(
    name: str, protocol: str, contact_name: str, body: ContactUpdateRequest, request: Request
) -> dict:
    updates: dict[str, Any] = {}
    if body.details is not None:
        updates["details"] = body.details
    if body.preference is not None:
        updates["preference"] = body.preference
    await request.app.state.source.update_contact_method(name, protocol, contact_name, **updates)
    return {"database": name, "protocol": protocol, "name": contact_name, "updated": True}


@router.delete(
    "/{name}/contacts/{protocol}/{contact_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove contact method",
)
async def remove_contact(name: str, protocol: str, contact_name: str, request: Request) -> None:
    await request.app.state.source.remove_contact_method(name, protocol, contact_name)
