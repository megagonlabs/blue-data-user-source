from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
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

    def interact(self, interaction_id: str | None = None) -> InteractionManager:
        """Build an InteractionManager for this contact method.

        ``interaction_id`` lets a caller (e.g. SessionManager) supply the id
        used to correlate an async reply, so the same id backs both the
        transport-level pending_interactions Future and any durable record
        the caller keeps. When omitted, protocols that need one generate
        their own (existing standalone-usage behavior).
        """
        if self.protocol == "stdio":
            return self._stdio_manager(interaction_id)
        if self.protocol == "webhook":
            return self._webhook_manager(interaction_id)
        if self.protocol == "email":
            return self._email_manager(interaction_id)
        raise InteractionError(
            f"Contact protocol '{self.protocol}' requires a registered handler."
        )

    def _stdio_manager(self, interaction_id: str | None = None) -> InteractionManager:  # noqa: ARG002 — stdio has no async correlation to key
        async def _start() -> None:
            pass

        async def _respond(message: str) -> str:
            sys.stdout.write(f"\n{message}\n> ")
            sys.stdout.flush()
            return sys.stdin.readline().rstrip("\n")

        async def _stop() -> None:
            pass

        return InteractionManager(on_start=_start, on_response=_respond, on_stop=_stop)

    def _webhook_manager(self, interaction_id: str | None = None) -> InteractionManager:
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

            iid = interaction_id or str(uuid4())
            loop = asyncio.get_running_loop()
            future: asyncio.Future[str] = loop.create_future()
            pending_interactions[iid] = future

            response_url = f"{response_base_url}/interactions/{iid}/response"
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        url,
                        json={
                            "interaction_id": iid,
                            "message": message,
                            "response_url": response_url,
                        },
                        headers=headers,
                        timeout=10.0,
                    )
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                raise InteractionError(
                    f"No response received within {timeout}s for interaction {iid!r}"
                )
            finally:
                pending_interactions.pop(iid, None)

        async def _stop() -> None:
            pass

        return InteractionManager(on_start=_start, on_response=_respond, on_stop=_stop)


    def _email_stdio_manager(self, interaction_id: str | None = None) -> InteractionManager:
        """Email contact method in stdio mode — for local development and testing.

        Prints a formatted email to stdout (To, From, Subject, Reply-To, body)
        and reads the reply from stdin. No SMTP connection is made and no
        pending_interactions Future is created.

        Required detail keys:
            address      — recipient email address (displayed in To: field)

        Optional detail keys:
            from_address — displayed in From: field (default: 'agent')
            reply_domain — used to construct a display-only Reply-To address
                           (default: 'localhost')
            subject      — email subject line (default: 'A question for you')
        """
        address: str = self.details["address"]
        from_address: str = self.details.get("from_address") or "agent"
        reply_domain: str = (self.details.get("reply_domain") or "localhost").lstrip("@")
        subject: str = self.details.get("subject") or "A question for you"

        async def _start() -> None:
            pass

        async def _respond(message: str) -> str:
            iid = interaction_id or str(uuid4())
            reply_to = f"interaction-{iid}@{reply_domain}"
            sys.stdout.write(
                f"\n{'─' * 60}\n"
                f"  To:       {address}\n"
                f"  From:     {from_address}\n"
                f"  Subject:  {subject}\n"
                f"  Reply-To: {reply_to}\n"
                f"{'─' * 60}\n"
                f"\n{message}\n\n"
                f"Reply: "
            )
            sys.stdout.flush()
            return sys.stdin.readline().rstrip("\n")

        async def _stop() -> None:
            pass

        return InteractionManager(on_start=_start, on_response=_respond, on_stop=_stop)

    def _email_manager(self, interaction_id: str | None = None) -> InteractionManager:
        """Outgoing email with async response via inbound email webhook or reply link.

        Required detail keys:
            address           — recipient email address
            from_address      — sender address (e.g. 'Agent <agent@example.com>')
            smtp_host         — SMTP server hostname (not required when inbound_provider='stdio')
            reply_domain      — domain for Reply-To: interaction-{id}@reply_domain
            response_base_url — base URL of the user source REST API
                                (not required when inbound_provider='stdio')

        Optional detail keys:
            inbound_provider  — 'mailgun', 'postmark', 'sendgrid', 'smtp_server', or 'stdio'
                                (default: none — email is sent, response via webhook or link)
                                Use 'stdio' for local development: prints email to stdout,
                                reads reply from stdin — no SMTP connection required.
            smtp_port         — SMTP port (default: 587)
            smtp_user         — SMTP username (default: from_address)
            smtp_password     — SMTP password
            smtp_use_tls      — use STARTTLS (default: True)
            subject           — email subject (default: 'A question for you')
            timeout           — seconds to wait for response (default: 300)
        """
        if self.details.get("inbound_provider") == "stdio":
            return self._email_stdio_manager(interaction_id)

        address: str = self.details["address"]
        from_address: str = self.details["from_address"]
        smtp_host: str = self.details["smtp_host"]
        reply_domain: str = self.details["reply_domain"].lstrip("@")
        response_base_url: str = self.details["response_base_url"].rstrip("/")
        smtp_port: int = int(self.details.get("smtp_port", 587))
        smtp_user: str = self.details.get("smtp_user") or from_address
        smtp_password: str = self.details.get("smtp_password") or ""
        smtp_use_tls: bool = bool(self.details.get("smtp_use_tls", True))
        subject: str = self.details.get("subject") or "A question for you"
        timeout: float = float(self.details.get("timeout", 300))

        async def _start() -> None:
            pass

        async def _respond(message: str) -> str:
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            import aiosmtplib

            iid = interaction_id or str(uuid4())
            loop = asyncio.get_running_loop()
            future: asyncio.Future[str] = loop.create_future()
            pending_interactions[iid] = future

            reply_to = f"interaction-{iid}@{reply_domain}"
            respond_link = f"{response_base_url}/interactions/{iid}/respond"

            body_text = (
                f"{message}\n\n"
                f"Reply to this email with your answer, or click the link below:\n"
                f"{respond_link}"
            )
            body_html = (
                f"<p>{message}</p>"
                f"<p>Reply to this email with your answer, or "
                f'<a href="{respond_link}">click here</a> to respond.</p>'
            )

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_address
            msg["To"] = address
            msg["Reply-To"] = reply_to
            msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html, "html"))

            try:
                await aiosmtplib.send(
                    msg,
                    hostname=smtp_host,
                    port=smtp_port,
                    username=smtp_user,
                    password=smtp_password,
                    start_tls=smtp_use_tls,
                )
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                raise InteractionError(
                    f"No email response within {timeout}s for interaction {iid!r}"
                )
            finally:
                pending_interactions.pop(iid, None)

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
        if len(methods) == 1:
            return methods[0]
        return await self._choose_contact_method(methods)

    async def _choose_contact_method(self, methods: list[ContactMethod]) -> ContactMethod:
        """Ask an LLM to pick among several available contact methods.

        Falls back to the lowest-``preference`` method if the LLM call fails
        or returns a choice that isn't one of the options.
        """
        from blue_data_user_source.reasoning.reasoner import _llm_complete

        fallback = min(methods, key=lambda m: m.preference)

        preferred_channel = self._data_manager.get_metadata("availability.preferred_channel")
        working_hours = self._data_manager.get_metadata("availability.working_hours")
        now = datetime.now(timezone.utc)

        options = "\n".join(
            f"- protocol={m.protocol!r}, name={m.name!r}, preference={m.preference} "
            "(lower preference = more favored)"
            for m in methods
        )
        prompt = (
            "Choose the best contact method to reach a user right now, from the options below.\n\n"
            f"Available contact methods:\n{options}\n\n"
            f"User's stated preferred channel (free text, may be empty or not match any option): "
            f"{preferred_channel or 'not specified'}\n"
            f"User's working hours (free text): {working_hours or 'not specified'}\n"
            f"Current time (UTC): {now.strftime('%A, %Y-%m-%d %H:%M')}\n\n"
            "Weigh the stated preferred channel and working hours alongside each method's "
            "preference ranking. Pick exactly one method from the list above. "
            'Return only a JSON object: {"protocol": "<protocol>", "name": "<name>"}'
        )
        result = await _llm_complete(prompt, properties={"response_format": "json_object"})
        if isinstance(result, dict):
            for method in methods:
                if method.protocol == result.get("protocol") and method.name == result.get("name"):
                    return method
        return fallback
