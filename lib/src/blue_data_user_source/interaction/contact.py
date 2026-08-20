from __future__ import annotations

import asyncio
import sys
from typing import Any
from uuid import uuid4

from blue_data_user_source.interaction.manager import InteractionManager
from blue_data_user_source.interaction.pending import pending_interactions
from blue_data_user_source.types import InteractionError


class ContactMethod:
    """Stores metadata for one contact channel and provides an InteractionManager."""

    SUPPORTED_PROTOCOLS = frozenset(
        {"session", "email", "sms", "stdio", "messaging", "enterprise", "notification", "webhook"}
    )

    def __init__(self, protocol: str, name: str, details: dict[str, Any]) -> None:
        if protocol not in self.SUPPORTED_PROTOCOLS:
            raise InteractionError(f"Unsupported contact protocol: {protocol}")
        self.protocol = protocol
        self.name = name
        self.details = details

    @property
    def preference(self) -> int:
        return int(self.details.get("preference", 0))

    def interact(self) -> InteractionManager:
        if self.protocol == "stdio":
            return self._stdio_manager()
        if self.protocol == "webhook":
            return self._webhook_manager()
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

    def _webhook_manager(self) -> InteractionManager:
        """Outgoing webhook with async response via the user source REST API.

        Required detail keys:
            url               — POST target for outgoing questions
            response_base_url — base URL of the user source REST API
                                (response_url sent in payload:
                                 {response_base_url}/interactions/{id}/response)

        Optional detail keys:
            headers           — extra HTTP headers for the outgoing POST
            timeout           — seconds to wait for a response (default: 300)
        """
        url: str = self.details["url"]
        response_base_url: str = self.details["response_base_url"].rstrip("/")
        headers: dict[str, str] = self.details.get("headers") or {}
        timeout: float = float(self.details.get("timeout", 300))

        async def _start() -> None:
            pass

        async def _respond(message: str) -> str:
            import httpx

            interaction_id = str(uuid4())
            loop = asyncio.get_running_loop()
            future: asyncio.Future[str] = loop.create_future()
            pending_interactions[interaction_id] = future

            response_url = f"{response_base_url}/interactions/{interaction_id}/response"
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        url,
                        json={
                            "interaction_id": interaction_id,
                            "message": message,
                            "response_url": response_url,
                        },
                        headers=headers,
                        timeout=10.0,
                    )
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                raise InteractionError(
                    f"No response received within {timeout}s for interaction {interaction_id!r}"
                )
            finally:
                pending_interactions.pop(interaction_id, None)

        async def _stop() -> None:
            pass

        return InteractionManager(on_start=_start, on_response=_respond, on_stop=_stop)


class ContactManager:
    """Manages contact methods stored as contacts.{protocol}.{name} in the contact JSONSource."""

    def __init__(self, database: str, data_manager: Any) -> None:
        self._database = database
        self._data_manager = data_manager

    def _store(self) -> Any:
        return self._data_manager.get_contact_source()

    # ------------------------------------------------------------------ #
    # CRUD                                                                 #
    # ------------------------------------------------------------------ #

    async def create_contact_method(
        self,
        protocol: str,
        name: str,
        details: dict[str, Any],
        preference: int = 0,
    ) -> None:
        if protocol not in ContactMethod.SUPPORTED_PROTOCOLS:
            raise InteractionError(f"Unsupported contact protocol: {protocol!r}")
        entry = {**details, "preference": preference}
        self._store().set(f"contacts.{protocol}.{name}", entry)

    async def get_contact_method(self, protocol: str, name: str) -> ContactMethod | None:
        entry = self._store().get(f"contacts.{protocol}.{name}")
        if entry is None:
            return None
        return ContactMethod(protocol=protocol, name=name, details=entry)

    async def update_contact_method(
        self, protocol: str, name: str, **updates: Any
    ) -> None:
        store = self._store()
        entry = store.get(f"contacts.{protocol}.{name}")
        if entry is None:
            raise InteractionError(f"Contact method {protocol!r}/{name!r} not found.")
        entry.update(updates)
        store.set(f"contacts.{protocol}.{name}", entry)

    async def delete_contact_method(self, protocol: str, name: str) -> None:
        self._store().delete(f"contacts.{protocol}.{name}")

    # ------------------------------------------------------------------ #
    # Listing                                                              #
    # ------------------------------------------------------------------ #

    async def list_contact_methods(
        self, protocol: str | None = None
    ) -> list[ContactMethod]:
        all_contacts: dict[str, Any] = self._store().get("contacts") or {}
        protocols = {protocol: all_contacts[protocol]} if protocol else all_contacts
        methods: list[ContactMethod] = []
        for proto, entries in protocols.items():
            if not isinstance(entries, dict):
                continue
            for entry_name, details in entries.items():
                if not isinstance(details, dict):
                    continue
                try:
                    methods.append(ContactMethod(protocol=proto, name=entry_name, details=details))
                except InteractionError:
                    continue
        return methods

    async def list_protocols(self) -> list[str]:
        all_contacts: dict[str, Any] = self._store().get("contacts") or {}
        return [p for p, v in all_contacts.items() if isinstance(v, dict)]

    async def list_named_entries(self, protocol: str) -> dict[str, dict]:
        entries = self._store().get(f"contacts.{protocol}") or {}
        return {k: v for k, v in entries.items() if isinstance(v, dict)}

    # ------------------------------------------------------------------ #
    # Preferred channel                                                    #
    # ------------------------------------------------------------------ #

    async def identify_contact_method(self) -> ContactMethod:
        methods = await self.list_contact_methods()
        if not methods:
            return ContactMethod(protocol="stdio", name="default", details={})
        return min(methods, key=lambda m: m.preference)
