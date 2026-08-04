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
    """Manages contact methods for a user stored in the contact JSONSource."""

    def __init__(self, database: str, data_manager: Any) -> None:
        self._database = database
        self._data_manager = data_manager

    def _store(self) -> Any:
        return self._data_manager.get_contact_source()

    async def create_contact_method(
        self,
        name: str,
        protocol: str,
        details: dict[str, Any],
        preference: int = 0,
    ) -> None:
        if protocol not in ContactMethod.SUPPORTED_PROTOCOLS:
            raise InteractionError(f"Unsupported contact protocol: {protocol!r}")
        self._store().set(f"contacts.{name}", {
            "protocol": protocol,
            "details": details,
            "preference": preference,
        })

    async def get_contact_method(self, name: str) -> ContactMethod | None:
        entry = self._store().get(f"contacts.{name}")
        if entry is None:
            return None
        return ContactMethod(details=entry.get("details", {}), protocol=entry["protocol"])

    async def update_contact_method(self, name: str, **updates: Any) -> None:
        store = self._store()
        entry = store.get(f"contacts.{name}")
        if entry is None:
            raise InteractionError(f"Contact method {name!r} not found.")
        if "protocol" in updates and updates["protocol"] not in ContactMethod.SUPPORTED_PROTOCOLS:
            raise InteractionError(f"Unsupported contact protocol: {updates['protocol']!r}")
        entry.update(updates)
        store.set(f"contacts.{name}", entry)

    async def delete_contact_method(self, name: str) -> None:
        self._store().delete(f"contacts.{name}")

    async def list_contact_methods(
        self, protocol: str | None = None
    ) -> list[ContactMethod]:
        all_contacts: dict[str, Any] = self._store().get("contacts") or {}
        methods: list[ContactMethod] = []
        for entry in all_contacts.values():
            proto = str(entry.get("protocol", "stdio"))
            if protocol is not None and proto != protocol:
                continue
            try:
                methods.append(ContactMethod(details=entry.get("details", {}), protocol=proto))
            except InteractionError:
                continue
        return methods

    async def identify_contact_method(self) -> ContactMethod:
        methods = await self.list_contact_methods()
        if not methods:
            return ContactMethod(details={}, protocol="stdio")
        return min(methods, key=lambda m: m.details.get("preference", 999))
