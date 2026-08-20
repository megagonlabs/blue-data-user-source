"""Sendgrid inbound email (Inbound Parse) adapter.

Sendgrid POSTs multipart/form-data. Relevant fields:

    to      — recipient address(es), e.g. interaction-<id>@udb.example.com
    text    — plain-text body (Sendgrid does not strip quoted text server-side;
              we use a simple heuristic to remove the quoted portion)

Docs: https://www.twilio.com/docs/sendgrid/for-developers/parsing-email/setting-up-the-inbound-parse-webhook
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs

from blue_data_user_source.interaction.email.adapter import InboundEmailAdapter

# Lines that start a quoted block in email replies.
_QUOTE_MARKERS = re.compile(
    r"^(-{3,}|_{3,}|"                  # horizontal rules used as separators
    r"On .+wrote:|"                      # "On <date>, <person> wrote:"
    r">)",                               # standard > quote prefix
    re.IGNORECASE | re.MULTILINE,
)


def _strip_quoted(text: str) -> str:
    """Return the text above the first quoted-reply marker."""
    match = _QUOTE_MARKERS.search(text)
    if match:
        return text[: match.start()].rstrip()
    return text.strip()


class SendgridAdapter(InboundEmailAdapter):
    def extract(
        self, body: bytes, content_type: str, headers: dict[str, str]
    ) -> tuple[str, str]:
        decoded = body.decode("utf-8", errors="replace")
        parsed = parse_qs(decoded, keep_blank_values=True)

        def _first(key: str) -> str:
            return (parsed.get(key) or [""])[0]

        recipient = _first("to") or _first("To")
        if not recipient:
            raise ValueError("Sendgrid payload missing 'to' field")

        interaction_id = self._id_from_address(self._first_address(recipient))

        raw_text = _first("text") or _first("plain")
        if not raw_text:
            raise ValueError("Sendgrid payload has no plain-text body ('text')")

        reply_text = _strip_quoted(raw_text)
        if not reply_text:
            raise ValueError("Sendgrid payload: reply text is empty after stripping quoted content")

        return interaction_id, reply_text
