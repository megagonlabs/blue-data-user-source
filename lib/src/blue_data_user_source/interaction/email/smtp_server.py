"""SMTP server adapter (future).

When implemented, this adapter will drive an aiosmtpd listener that accepts
inbound SMTP connections directly (requires an MX record pointing at the
host running the server, plus port 25 open).

For now it raises NotImplementedError so the provider name is registered and
discoverable, but attempting to use it fails clearly.

Implementation notes for a future contributor
---------------------------------------------
* Use aiosmtpd's `Controller` to bind an SMTP listener.
* Parse the raw RFC 2822 message with `email.message_from_bytes`.
* Extract the interaction id from the `To:` header local part.
* Strip quoted text with `email-reply-parser` (PyPI: email-reply-parser).
* Resolve the pending_interactions Future from the parsed reply.

The `extract` method on this class would receive the raw message bytes in
`body` (populated by the listener handler) with content_type='message/rfc822'.
"""
from __future__ import annotations

from blue_data_user_source.interaction.email.adapter import InboundEmailAdapter


class SMTPServerAdapter(InboundEmailAdapter):
    def extract(
        self, body: bytes, content_type: str, headers: dict[str, str]
    ) -> tuple[str, str]:
        raise NotImplementedError(
            "The smtp_server inbound provider is not yet implemented. "
            "Use 'mailgun', 'postmark', or 'sendgrid' for inbound email handling, "
            "or implement aiosmtpd-based processing here."
        )
