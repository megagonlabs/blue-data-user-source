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

from abc import ABC, abstractmethod


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

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _id_from_address(address: str) -> str:
        """Extract the interaction id from 'interaction-<id>@domain'."""
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
        """Return the first email address from a comma-separated To/Recipient header."""
        return raw.split(",")[0].strip().split()[-1].strip("<>")


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
