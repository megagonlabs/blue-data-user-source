"""Mailgun inbound email adapter.

Mailgun POSTs form-encoded data when an email arrives. Relevant fields:

    recipient      — full To address, e.g. interaction-<id>@udb.example.com
    stripped-text  — reply body with quoted text and signatures removed
    body-plain     — full plain-text body (fallback if stripped-text is empty)

Docs: https://documentation.mailgun.com/docs/mailgun/user-manual/receive-forward-store/
"""
from __future__ import annotations

from urllib.parse import parse_qs

from blue_data_user_source.interaction.email.adapter import InboundEmailAdapter


class MailgunAdapter(InboundEmailAdapter):
    def extract(
        self, body: bytes, content_type: str, headers: dict[str, str]
    ) -> tuple[str, str]:
        parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)

        def _first(key: str) -> str:
            return (parsed.get(key) or [""])[0]

        recipient = _first("recipient") or _first("To")
        if not recipient:
            raise ValueError("Mailgun payload missing 'recipient' field")

        interaction_id = self._id_from_address(self._first_address(recipient))

        reply_text = _first("stripped-text") or _first("body-plain")
        if not reply_text:
            raise ValueError("Mailgun payload has no reply text ('stripped-text' / 'body-plain')")

        return interaction_id, reply_text.strip()
