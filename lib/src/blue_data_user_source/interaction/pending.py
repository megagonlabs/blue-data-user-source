from __future__ import annotations

import asyncio
import time
from typing import Any, Literal
from uuid import UUID

# Interaction id → Future that resolves to the human's reply text, in the process
# that asked. Created when a question is sent by webhook or email; resolved by
# deliver_reply when the reply reaches that same process.
pending_interactions: dict[str, asyncio.Future[str]] = {}

# How often a waiting process looks for a reply that reached another one.
REPLY_POLL_SECONDS = 1.0

_RECORD = "interaction"

ReplyOutcome = Literal["accepted", "resolved", "unknown"]


class ReplyBox:
    """Pending interactions in a source's outer registry, for replies between processes.

    A question asked by the MCP server or the CLI is answered through
    ``blue-userdb-api``, another process, which sees only the interaction id
    (#197). The outer registry is the store they share: a record per pending
    interaction, into which the reply is written for the asker to pick up.
    """

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def open(self, interaction_id: str, timeout: float) -> None:
        self._registry.register_record(
            name=interaction_id, type=_RECORD, scope="/",
            description="a question waiting for its reply",
            properties={"reply": None, "expires_at": time.time() + timeout},
        )

    def _properties(self, interaction_id: str) -> dict[str, Any] | None:
        """The live record of *interaction_id*. The asker may have died, so one past
        its deadline is gone; the id comes from the outside, so anything else is too."""
        try:
            UUID(interaction_id)
        except ValueError:
            return None
        record = self._registry.get_record(interaction_id, _RECORD, "/")
        if record is None:
            return None
        properties = record.get("properties") or {}
        if properties.get("expires_at", 0) < time.time():
            self.close(interaction_id)
            return None
        return properties

    def is_pending(self, interaction_id: str) -> bool:
        properties = self._properties(interaction_id)
        return properties is not None and properties.get("reply") is None

    def deliver(self, interaction_id: str, text: str) -> ReplyOutcome:
        properties = self._properties(interaction_id)
        if properties is None:
            return "unknown"
        if properties.get("reply") is not None:
            return "resolved"
        self._registry.set_record_property(interaction_id, _RECORD, "/", "reply", text)
        return "accepted"

    def reply(self, interaction_id: str) -> str | None:
        return (self._properties(interaction_id) or {}).get("reply")

    def close(self, interaction_id: str) -> None:
        if self._registry.get_record(interaction_id, _RECORD, "/") is not None:
            self._registry.deregister_record(interaction_id, _RECORD, "/")


def deliver_reply(replies: ReplyBox, interaction_id: str, text: str) -> ReplyOutcome:
    """Hand *text* to whichever process is waiting for it, this one first."""
    future = pending_interactions.get(interaction_id)
    if future is None:
        return replies.deliver(interaction_id, text)
    if future.done():
        return "resolved"
    future.set_result(text)
    return "accepted"


def is_reply_pending(replies: ReplyBox, interaction_id: str) -> bool:
    future = pending_interactions.get(interaction_id)
    return replies.is_pending(interaction_id) if future is None else not future.done()


async def wait_for_reply(
    interaction_id: str, future: asyncio.Future[str], timeout: float, replies: ReplyBox | None,
) -> str:
    """The reply, from *future* or, with *replies*, from another process. Raises
    ``asyncio.TimeoutError`` after *timeout* seconds."""
    if replies is None:
        return await asyncio.wait_for(future, timeout=timeout)

    async def poll() -> str:
        while (reply := replies.reply(interaction_id)) is None:
            await asyncio.sleep(REPLY_POLL_SECONDS)
        return reply

    poller = asyncio.ensure_future(poll())
    try:
        done, _ = await asyncio.wait(
            {future, poller}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        poller.cancel()
    if not done:
        raise asyncio.TimeoutError
    return done.pop().result()
