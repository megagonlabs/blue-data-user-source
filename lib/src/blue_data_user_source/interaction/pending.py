from __future__ import annotations

import asyncio

# Interaction id → Future that resolves to the human's reply text.
# Created by WebhookContactMethod._webhook_manager when a question is sent;
# resolved by the REST API's POST /interactions/{interaction_id}/response handler.
pending_interactions: dict[str, asyncio.Future[str]] = {}
