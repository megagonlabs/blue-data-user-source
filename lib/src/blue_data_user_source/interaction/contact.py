from __future__ import annotations

import sys
from typing import Any

from blue_data_user_source.interaction.manager import InteractionManager
from blue_data_user_source.types import InteractionError


class ContactMethod:
    """Stores metadata for one contact channel and provides an InteractionManager."""

    SUPPORTED_PROTOCOLS = frozenset(
        {"session", "email", "sms", "stdio", "messaging", "enterprise", "notification"}
    )

    def __init__(self, details: dict[str, Any], protocol: str) -> None:
        if protocol not in self.SUPPORTED_PROTOCOLS:
            raise InteractionError(f"Unsupported contact protocol: {protocol}")
        self.details = details
        self.protocol = protocol

    def interact(self) -> InteractionManager:
        """Return an InteractionManager configured for this contact method."""
        if self.protocol == "stdio":
            return self._stdio_manager()
        raise InteractionError(
            f"Contact protocol '{self.protocol}' requires a registered handler."
        )

    def _stdio_manager(self) -> InteractionManager:
        async def _start() -> None:
            pass

        async def _respond(message: str) -> str:
            sys.stdout.write(f"\n{message}\n> ")
            sys.stdout.flush()
            return sys.stdin.readline().rstrip("\n")

        async def _stop() -> None:
            pass

        return InteractionManager(on_start=_start, on_response=_respond, on_stop=_stop)


class ContactManager:
    """Manages contact methods for a user and selects the best channel."""

    def __init__(self, database: str, data_manager: Any) -> None:
        self._database = database
        self._data_manager = data_manager

    async def identify_contact_method(self, query: str) -> ContactMethod:
        """Return the ContactMethod most suitable for the given interaction context."""
        methods = await self.get_contact_methods()
        if not methods:
            return ContactMethod(details={}, protocol="stdio")
        # Prefer the method with the lowest preference value (highest priority).
        return min(methods, key=lambda m: m.details.get("preference", 999))

    async def get_contact_methods(
        self, name: str | None = None, protocol: str | None = None
    ) -> list[ContactMethod]:
        """Return all contact methods, optionally filtered by name or protocol."""
        try:
            raw: list[dict[str, Any]] = await self._data_manager._registries[
                self._database
            ].execute_json(f"$.{self._database}.metadata.contacts[*]")
        except KeyError:
            raw = []

        methods: list[ContactMethod] = []
        for entry in raw:
            proto = str(entry.get("type", "stdio"))
            if protocol is not None and proto != protocol:
                continue
            if name is not None and entry.get("name") != name:
                continue
            try:
                methods.append(ContactMethod(details=entry, protocol=proto))
            except InteractionError:
                continue

        return methods
