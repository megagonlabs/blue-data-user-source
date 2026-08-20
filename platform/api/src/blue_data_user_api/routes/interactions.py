from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from blue_data_user_api.auth import require_api_key
from blue_data_user_source.interaction.pending import pending_interactions

router = APIRouter(prefix="/interactions", tags=["interactions"], dependencies=[Depends(require_api_key)])


class InteractionResponse(BaseModel):
    text: str


@router.post("/{interaction_id}/response", status_code=status.HTTP_200_OK, summary="Post response to a pending interaction")
async def post_response(interaction_id: str, body: InteractionResponse) -> dict:
    future = pending_interactions.get(interaction_id)
    if future is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No pending interaction with id {interaction_id!r}",
        )
    if future.done():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Interaction {interaction_id!r} already resolved",
        )
    future.set_result(body.text)
    return {"interaction_id": interaction_id, "accepted": True}
