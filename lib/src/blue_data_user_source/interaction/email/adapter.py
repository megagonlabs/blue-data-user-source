"""Inbound email adapter interface and registry.

An adapter converts an inbound email webhook payload into (interaction_id, reply_text).
It operates on raw bytes + metadata so it has no dependency on any web framework.

The interaction_id is embedded in the recipient address as the local-part prefix:
    interaction-<uuid>@<reply_domain>

Each provider exposes the recipient address and a pre-stripped reply body in
different shapes; the adapter handles both.

Adding a provider
-----------------
1. Create a module in this package that implements InboundEmailAdapter.
2. Register an instance in _ADAPTERS below.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from email.parser import BytesParser
from email.policy import HTTP
from email.utils import collapse_rfc2231_value
from urllib.parse import parse_qs


class InboundEmailAdapter(ABC):
    """Parse a raw inbound webhook request into (interaction_id, reply_text).

    The web framework layer reads the raw request body and headers and passes
    them here; the adapter is framework-agnostic.
    """

    @abstractmethod
    def extract(
        self, body: bytes, content_type: str, headers: dict[str, str]
    ) -> tuple[str, str]:
        """Return (interaction_id, reply_text).

        Raises ValueError if the payload cannot be parsed or the interaction id
        cannot be found.
        """
        ...

    def parse(
        self, body: bytes, content_type: str, headers: dict[str, str]
    ) -> tuple[str, str]:
        """:meth:`extract`, with any other parsing error raised as ``ValueError``.

        The inbound webhook is open (#170), so its payload is anyone's: a
        malformed one must be answered 422, and an adapter that trips over an
        unexpected shape (``IndexError``, ``AttributeError``…) answered 500
        (#184). Callers use this; adapters implement :meth:`extract`.
        """
        try:
            return self.extract(body, content_type, headers)
        except (TypeError, AttributeError, IndexError, KeyError) as exc:
            raise ValueError(f"Malformed {type(self).__name__} payload: {type(exc).__name__}: {exc}") from exc

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _form_fields(body: bytes, content_type: str) -> dict[str, list[str]]:
        """Parse a webhook form body, ``multipart/form-data`` or URL-encoded.

        Providers post multipart (SendGrid always does), which ``parse_qs``
        cannot read. File parts (attachments) are skipped. A part is decoded with
        its own charset, else the one a ``charsets`` field (SendGrid's JSON map
        of field name to charset) names for it, else UTF-8.
        """
        if not content_type.lower().startswith("multipart/form-data"):
            return parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)

        message = BytesParser(policy=HTTP).parsebytes(
            b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + body
        )
        if not message.is_multipart():
            raise ValueError("multipart/form-data body has no parts (missing or wrong boundary?)")
        raw: list[tuple[str, bytes, str | None]] = []
        for part in message.iter_parts():
            raw_name = part.get_param("name", header="content-disposition")
            if raw_name is None or part.get_filename() is not None:
                continue
            # get_param is typed to return a (charset, language, value) tuple for
            # an RFC 2231-encoded name (name*=utf-8''to), and does under the
            # compat32 policy; the HTTP policy used here already decodes it.
            # Collapsing makes the field name a str under either (#152).
            name = collapse_rfc2231_value(raw_name)
            payload = part.get_payload(decode=True)  # typed to allow a nested Message; a form field is bytes
            raw.append((name, payload if isinstance(payload, bytes) else b"", part.get_content_charset()))

        charsets: dict[str, str] = {}
        for name, payload, _ in raw:
            if name == "charsets":
                try:
                    charsets = {k: str(v) for k, v in json.loads(payload.decode("ascii")).items()}
                except (ValueError, AttributeError):
                    charsets = {}

        fields: dict[str, list[str]] = {}
        for name, payload, charset in raw:
            encoding = charset or charsets.get(name) or "utf-8"
            try:
                text = payload.decode(encoding, errors="replace")
            except LookupError:  # unknown charset name
                text = payload.decode("utf-8", errors="replace")
            fields.setdefault(name, []).append(text)
        return fields

    @staticmethod
    def _id_from_address(address: str) -> str:
        """Extract the interaction id from 'interaction-<id>@domain'."""
        if not isinstance(address, str):
            raise ValueError(f"Recipient address {address!r} is not a string")
        local = address.split("@")[0]
        prefix = "interaction-"
        if not local.startswith(prefix):
            raise ValueError(
                f"Recipient address {address!r} does not carry an interaction id "
                f"(expected local part to start with '{prefix}')"
            )
        return local[len(prefix):]

    @staticmethod
    def _first_address(raw: str) -> str:
        """Return the first email address from a comma-separated To/Recipient header.

        Raises ValueError for a value that is not a string or names no address (#184).
        """
        if not isinstance(raw, str):
            raise ValueError(f"Recipient {raw!r} is not a string")
        words = raw.split(",")[0].split()
        if not words:
            raise ValueError(f"No recipient address in {raw!r}")
        return words[-1].strip("<>")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _load_adapters() -> dict[str, InboundEmailAdapter]:
    from blue_data_user_source.interaction.email.mailgun import MailgunAdapter
    from blue_data_user_source.interaction.email.postmark import PostmarkAdapter
    from blue_data_user_source.interaction.email.sendgrid import SendgridAdapter
    from blue_data_user_source.interaction.email.smtp_server import SMTPServerAdapter

    return {
        "mailgun": MailgunAdapter(),
        "postmark": PostmarkAdapter(),
        "sendgrid": SendgridAdapter(),
        "smtp_server": SMTPServerAdapter(),
    }


_adapters: dict[str, InboundEmailAdapter] | None = None


def get_adapter(provider: str) -> InboundEmailAdapter:
    global _adapters
    if _adapters is None:
        _adapters = _load_adapters()
    adapter = _adapters.get(provider)
    if adapter is None:
        known = ", ".join(sorted(_adapters))
        raise ValueError(f"Unknown inbound email provider {provider!r}. Known: {known}")
    return adapter


def supported_providers() -> list[str]:
    global _adapters
    if _adapters is None:
        _adapters = _load_adapters()
    return sorted(_adapters)
