from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from blue_data_user_api.auth import require_api_key
from blue_data_user_source.interaction.pending import pending_interactions

router = APIRouter(prefix="/interactions", tags=["interactions"])


# ---------------------------------------------------------------------------
# Webhook / REST response
# ---------------------------------------------------------------------------

class InteractionResponse(BaseModel):
    text: str


@router.post(
    "/{interaction_id}/response",
    status_code=status.HTTP_200_OK,
    summary="Post response to a pending interaction",
    dependencies=[Depends(require_api_key)],
)
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


# ---------------------------------------------------------------------------
# HTML form fallback (link in email body)
# No API key required — the interaction_id itself acts as a bearer token.
# ---------------------------------------------------------------------------

@router.get(
    "/{interaction_id}/respond",
    response_class=HTMLResponse,
    summary="HTML form for responding to a pending interaction (email link fallback)",
    include_in_schema=False,
)
async def respond_form(interaction_id: str) -> HTMLResponse:
    future = pending_interactions.get(interaction_id)
    if future is None or future.done():
        return HTMLResponse(
            content=_page("Interaction not found or already resolved",
                          "<p>This interaction has expired or was already answered.</p>"),
            status_code=404,
        )
    form_html = f"""
<form method="POST" action="/interactions/{interaction_id}/respond">
  <label for="text">Your response:</label><br><br>
  <textarea id="text" name="text" rows="6" cols="60" autofocus
            placeholder="Type your answer here…"></textarea><br><br>
  <button type="submit">Send response</button>
</form>
"""
    return HTMLResponse(content=_page("Respond to question", form_html))


@router.post(
    "/{interaction_id}/respond",
    response_class=HTMLResponse,
    summary="Submit the HTML form response",
    include_in_schema=False,
)
async def respond_form_submit(interaction_id: str, request: Request) -> HTMLResponse:
    form = await request.form()
    text = (form.get("text") or "").strip()
    if not text:
        return HTMLResponse(
            content=_page("Empty response", "<p>Please enter a response before submitting.</p>"),
            status_code=400,
        )
    future = pending_interactions.get(interaction_id)
    if future is None or future.done():
        return HTMLResponse(
            content=_page("Already answered", "<p>This interaction has already been resolved.</p>"),
            status_code=409,
        )
    future.set_result(text)
    return HTMLResponse(content=_page("Thank you", "<p>Your response has been received.</p>"))


# ---------------------------------------------------------------------------
# Inbound email webhook
# ---------------------------------------------------------------------------

@router.post(
    "/email/inbound",
    status_code=status.HTTP_200_OK,
    summary="Inbound email webhook — resolves a pending interaction from an email reply",
)
async def email_inbound(request: Request, provider: str = "mailgun") -> dict:
    """Accepts inbound email webhooks from Mailgun, Postmark, or Sendgrid.

    The `provider` query parameter selects the parsing adapter.
    Configure your provider to POST to this endpoint when an email arrives
    at your inbound domain (interaction-*@your-reply-domain.com).

    No API key is required — the interaction_id embedded in the recipient
    address acts as a bearer token.
    """
    from blue_data_user_source.interaction.email.adapter import get_adapter

    body = await request.body()
    content_type = request.headers.get("content-type", "")
    headers = dict(request.headers)

    try:
        adapter = get_adapter(provider)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    try:
        interaction_id, reply_text = adapter.extract(body, content_type, headers)
    except (ValueError, NotImplementedError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    future = pending_interactions.get(interaction_id)
    if future is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No pending interaction with id {interaction_id!r}",
        )
    if future.done():
        # Idempotent — email may be delivered more than once.
        return {"interaction_id": interaction_id, "accepted": False, "reason": "already resolved"}

    future.set_result(reply_text)
    return {"interaction_id": interaction_id, "accepted": True}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 560px;
          margin: 60px auto; padding: 0 16px; color: #1a1a1a; }}
  textarea {{ width: 100%; box-sizing: border-box; font-size: 1rem; padding: 8px; }}
  button {{ padding: 8px 20px; font-size: 1rem; cursor: pointer; }}
</style>
</head>
<body>
<h2>{title}</h2>
{body}
</body>
</html>"""
