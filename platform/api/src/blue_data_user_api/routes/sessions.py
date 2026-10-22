from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from blue_data_user_api.auth import SECURITY

router = APIRouter(tags=["sessions"], dependencies=SECURITY)


@router.post("/{name}/sessions", status_code=status.HTTP_201_CREATED, summary="Start a session")
async def create_session(name: str, request: Request) -> dict:
    session_id = await request.app.state.source.create_session(name)
    return {"database": name, "session_id": session_id}


@router.get("/{name}/sessions", summary="List sessions")
async def list_sessions(name: str, request: Request) -> dict:
    sessions = await request.app.state.source.list_sessions(name)
    return {"database": name, "sessions": sessions}


@router.get("/{name}/sessions/{session_id}", summary="Get a session")
async def get_session(name: str, session_id: str, request: Request) -> dict:
    record = await request.app.state.source.get_session(name, session_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return {"database": name, "session_id": session_id, **record}


@router.post("/{name}/sessions/{session_id}/end", summary="End a session")
async def end_session(name: str, session_id: str, request: Request) -> dict:
    await request.app.state.source.end_session(name, session_id)  # unknown session: 404 (app handlers)
    return {"database": name, "session_id": session_id, "ended": True}
