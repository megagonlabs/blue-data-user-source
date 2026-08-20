"""Postmark inbound email adapter.

Postmark POSTs JSON. Relevant fields:

    ToFull            — list of {Email, Name, MailboxHash} objects;
                        MailboxHash is the part between '+' and '@' in the
                        recipient address (Postmark hash addressing), but we
                        also accept parsing from the Email field directly.
    StrippedTextReply — reply body with quoted content removed (populated
                        when the message looks like a reply; may be empty for
                        top-level messages).
    TextBody          — full plain-text body (fallback).

Docs: https://postmarkapp.com/developer/webhooks/inbound-webhook
"""
from __future__ import annotations

import json

from blue_data_user_source.interaction.email.adapter import InboundEmailAdapter


class PostmarkAdapter(InboundEmailAdapter):
    def extract(
        self, body: bytes, content_type: str, headers: dict[str, str]
    ) -> tuple[str, str]:
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Postmark payload is not valid JSON: {exc}") from exc

        interaction_id: str | None = None

        # Prefer MailboxHash if it already holds the id directly.
        to_full = data.get("ToFull") or []
        for entry in to_full:
            hash_val = (entry.get("MailboxHash") or "").strip()
            if hash_val.startswith("interaction-"):
                interaction_id = hash_val[len("interaction-"):]
                break
            email = entry.get("Email") or ""
            if email:
                try:
                    interaction_id = self._id_from_address(email)
                    break
                except ValueError:
                    continue

        if not interaction_id:
            # Last resort: check the raw To header.
            raw_to = data.get("To") or ""
            try:
                interaction_id = self._id_from_address(self._first_address(raw_to))
            except ValueError:
                raise ValueError(
                    "Postmark payload: could not extract interaction id from ToFull or To"
                )

        reply_text = (data.get("StrippedTextReply") or data.get("TextBody") or "").strip()
        if not reply_text:
            raise ValueError("Postmark payload has no reply text ('StrippedTextReply' / 'TextBody')")

        return interaction_id, reply_text
