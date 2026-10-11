from __future__ import annotations

import asyncio
import copy
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from blue_data_user_source.data.paths import get_path
from blue_data_user_source.interaction.manager import InteractionManager
from blue_data_user_source.interaction.pending import pending_interactions
from blue_data_user_source.types import ContactNotFoundError, InteractionError, InteractionTimeoutError, LLMError

# ------------------------------------------------------------------ #
# Secrets in contact details (#143)                                    #
# ------------------------------------------------------------------ #

_CONTACT_SCHEMA = Path(__file__).parent.parent / "data" / "contact_schema.json"
MASK = "***"
_ENV_REF = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


def _secret_fields() -> dict[str, frozenset[str]]:
    """``{protocol: {field, ...}}`` for the fields the contact schema marks ``"secret": true``."""
    schema = json.loads(_CONTACT_SCHEMA.read_text())
    return {
        protocol: frozenset(f for f, spec in fields.items() if isinstance(spec, dict) and spec.get("secret"))
        for protocol, fields in schema.items()
    }


SECRET_FIELDS: dict[str, frozenset[str]] = _secret_fields()


def _mask(value: Any) -> Any:
    """Mask a secret value. A ``$VAR`` reference names a secret without holding it, so it is shown."""
    if isinstance(value, dict):
        return {k: _mask(v) for k, v in value.items()}
    if value in (None, "") or (isinstance(value, str) and _ENV_REF.fullmatch(value)):
        return value
    return MASK


def redact_details(protocol: str, details: dict[str, Any]) -> dict[str, Any]:
    """A copy of one contact's *details* with its secret fields masked, for any read path.

    Contacts carry credentials (an SMTP password, a webhook's Authorization
    header or secret URL). Returned by the REST API or an MCP tool, they would
    land in a client or an LLM's context, so every read path masks them.
    """
    secret = SECRET_FIELDS.get(protocol, frozenset())
    return {k: (_mask(v) if k in secret else copy.deepcopy(v)) for k, v in details.items()}


def _unmask(new: Any, stored: Any) -> Any:
    """*new* with every masked value (``***``) replaced by the stored one — per key for dicts."""
    if new == MASK:
        return stored
    if isinstance(new, dict) and isinstance(stored, dict):
        return {k: (stored.get(k) if v == MASK else v) for k, v in new.items()}
    return new


def redact_contacts(contacts: dict[str, Any]) -> dict[str, Any]:
    """A copy of a whole ``{protocol: {name: details}}`` contacts tree with secrets masked."""
    return {
        protocol: (
            {name: redact_details(protocol, d) if isinstance(d, dict) else d for name, d in entries.items()}
            if isinstance(entries, dict) else entries
        )
        for protocol, entries in contacts.items()
    }


def resolve_secret(value: Any) -> Any:
    """Resolve a ``$VAR`` reference from the environment, at the moment the secret is used.

    Storing ``"$SMTP_PASSWORD"`` instead of the password keeps it out of the
    contacts store. Other values are returned unchanged; dict values are
    resolved one by one (webhook headers).
    """
    if isinstance(value, dict):
        return {k: resolve_secret(v) for k, v in value.items()}
    match = _ENV_REF.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return value
    resolved = os.environ.get(match.group(1))
    if not resolved:
        raise InteractionError(f"Contact secret references ${match.group(1)}, which is not set in the environment.")
    return resolved


# A contact name is one segment of a dot-notation store path (#142).
_CONTACT_NAME = re.compile(r"[A-Za-z0-9 _@+-]{1,64}")

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_WORKING_HOURS_RE = re.compile(
    r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2}).*?"
    r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s*-\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*",
    re.IGNORECASE,
)


def _is_within_working_hours(
    working_hours: str | None, tz_name: str | None, now_utc: datetime
) -> bool | None:
    """Best-effort check of whether ``now_utc`` falls within a free-text working-hours
    window such as "09:00-17:00 Mon-Fri", localized to ``tz_name`` if given.

    Returns ``None`` (unknown) when the inputs are missing or don't match the
    supported "<start>-<end> ... <DayStart>-<DayEnd>" shape — callers should
    treat ``None`` as "don't know", not as "outside hours".
    """
    if not working_hours:
        return None
    match = _WORKING_HOURS_RE.search(working_hours)
    if not match:
        return None
    start_s, end_s, day_start, day_end = match.groups()
    try:
        tz = ZoneInfo(tz_name) if tz_name else timezone.utc
    except Exception:
        tz = timezone.utc
    local_now = now_utc.astimezone(tz)
    start_h, start_m = (int(p) for p in start_s.split(":"))
    end_h, end_m = (int(p) for p in end_s.split(":"))
    start_minutes, end_minutes = start_h * 60 + start_m, end_h * 60 + end_m
    now_minutes = local_now.hour * 60 + local_now.minute
    try:
        day_start_idx = _WEEKDAYS.index(day_start[:3].title())
        day_end_idx = _WEEKDAYS.index(day_end[:3].title())
    except ValueError:
        return None
    weekday = local_now.weekday()
    if day_start_idx <= day_end_idx:
        day_ok = day_start_idx <= weekday <= day_end_idx
    else:
        day_ok = weekday >= day_start_idx or weekday <= day_end_idx
    return day_ok and start_minutes <= now_minutes <= end_minutes


class ContactMethod:
    """Stores metadata for one contact channel and provides an InteractionManager."""

    SUPPORTED_PROTOCOLS = frozenset(
        {"session", "email", "sms", "stdio", "messaging", "enterprise", "notification", "webhook"}
    )

    # Protocols this release can actually reach the user through. The others
    # can be recorded (the contact schema describes them) but are never used.
    TRANSPORT_PROTOCOLS = frozenset({"stdio", "email", "webhook"})

    # Protocols that don't expect an immediate reply — favored when the user
    # is out of office or outside their stated working hours.
    ASYNC_PROTOCOLS = frozenset({"email", "webhook", "notification"})

    def __init__(self, protocol: str, name: str, details: dict[str, Any]) -> None:
        if protocol not in self.SUPPORTED_PROTOCOLS:
            raise InteractionError(f"Unsupported contact protocol: {protocol}")
        self.protocol = protocol
        self.name = name
        self.details = details

    @property
    def preference(self) -> int:
        return int(self.details.get("preference", 0))

    @property
    def is_async(self) -> bool:
        return self.protocol in self.ASYNC_PROTOCOLS

    def public_dict(self) -> dict[str, Any]:
        """``{protocol, name, details}`` with secret fields masked — what read paths return."""
        return {"protocol": self.protocol, "name": self.name, "details": redact_details(self.protocol, self.details)}

    @property
    def has_transport(self) -> bool:
        """True when this release can contact the user through this method (#129)."""
        return self.protocol in self.TRANSPORT_PROTOCOLS

    @property
    def uses_console(self) -> bool:
        """True when this method asks on the process's own stdout and reads stdin."""
        return self.protocol == "stdio" or (
            self.protocol == "email" and self.details.get("inbound_provider") == "stdio"
        )

    def _required(self, key: str) -> Any:
        """A required detail, or an ``InteractionError`` naming what is missing (#138)."""
        value = self.details.get(key)
        if value in (None, ""):
            raise InteractionError(f"{self.protocol} contact {self.name!r} is missing required field {key!r}.")
        return value

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
            f"Contact protocol '{self.protocol}' has no built-in transport in this release; "
            "only stdio, email and webhook can reach the user."
        )

    def _stdio_manager(self, interaction_id: str | None = None) -> InteractionManager:  # noqa: ARG002 — stdio has no async correlation to key
        async def _start() -> None:
            pass

        async def _respond(message: str) -> str:
            sys.stdout.write(f"\n{message}\n> ")
            sys.stdout.flush()
            return (await asyncio.to_thread(sys.stdin.readline)).rstrip("\n")

        async def _stop() -> None:
            pass

        return InteractionManager(on_start=_start, on_response=_respond, on_stop=_stop)

    def _webhook_manager(self, interaction_id: str | None = None) -> InteractionManager:
        """Outgoing webhook with async response via the user source REST API.

        Required detail keys:
            url               — POST target for outgoing questions
            response_base_url — base URL of the user source REST API
                                (response_url sent in payload:
                                 {response_base_url}/interactions/{interaction_id}/response)

        Optional detail keys:
            headers           — extra HTTP headers for the outgoing POST
            timeout           — seconds to wait for a response (default: 300)
        """
        url: str = resolve_secret(self._required("url"))
        response_base_url: str = self._required("response_base_url").rstrip("/")
        headers: dict[str, str] = resolve_secret(self.details.get("headers") or {})
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
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            url,
                            json={
                                "interaction_id": iid,
                                "message": message,
                                "response_url": response_url,
                            },
                            headers=headers,
                            timeout=10.0,
                        )
                        resp.raise_for_status()
                except httpx.HTTPError as exc:
                    # The question never reached the user (endpoint down, 4xx/5xx).
                    raise InteractionError(
                        f"webhook contact {self.name!r} could not deliver the question: {type(exc).__name__}: {exc}"
                    ) from exc
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                raise InteractionTimeoutError(
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
            return (await asyncio.to_thread(sys.stdin.readline)).rstrip("\n")

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

        address: str = self._required("address")
        from_address: str = self._required("from_address")
        smtp_host: str = self._required("smtp_host")
        reply_domain: str = self._required("reply_domain").lstrip("@")
        response_base_url: str = self._required("response_base_url").rstrip("/")
        smtp_port: int = int(self.details.get("smtp_port", 587))
        smtp_user: str = self.details.get("smtp_user") or from_address
        smtp_password: str = resolve_secret(self.details.get("smtp_password") or "")
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
            # The question can carry caller-shaped text (an LLM rewrite of the
            # query, or the raw query itself), so it must not be read as markup.
            message_html = html.escape(message).replace("\n", "<br>\n")
            body_html = (
                f"<p>{message_html}</p>"
                f"<p>Reply to this email with your answer, or "
                f'<a href="{html.escape(respond_link)}">click here</a> to respond.</p>'
            )

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_address
            msg["To"] = address
            msg["Reply-To"] = reply_to
            msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html, "html"))

            try:
                try:
                    await aiosmtplib.send(
                        msg,
                        hostname=smtp_host,
                        port=smtp_port,
                        username=smtp_user,
                        password=smtp_password,
                        start_tls=smtp_use_tls,
                    )
                except (aiosmtplib.SMTPException, OSError) as exc:
                    # The question never reached the user (server down, auth refused).
                    raise InteractionError(
                        f"email contact {self.name!r} could not send the question: {type(exc).__name__}: {exc}"
                    ) from exc
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                raise InteractionTimeoutError(
                    f"No email response within {timeout}s for interaction {iid!r}"
                )
            finally:
                pending_interactions.pop(iid, None)

        async def _stop() -> None:
            pass

        return InteractionManager(on_start=_start, on_response=_respond, on_stop=_stop)


class ContactManager:
    """Manages contact methods stored as contacts.{protocol}.{name} in the contact JSONSource."""

    def __init__(self, database: str, data_manager: Any, console: bool = True) -> None:
        """``console`` says whether this process has a console the user is at.

        Servers pass False: their stdin/stdout are not the user's (for the MCP
        stdio transport, stdout is the protocol stream), so methods that ask on
        the console are never selected there.
        """
        self._database = database
        self._data_manager = data_manager
        self._console = console

    def _store(self) -> Any:
        return self._data_manager.get_contact_source()

    # ------------------------------------------------------------------ #
    # CRUD                                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _path(protocol: str, name: str) -> str | None:
        """The store path of a contact, or None when *protocol*/*name* cannot name one.

        Both are interpolated into a dot-notation path, so a name like
        ``work.address`` used to address (and overwrite) a field of contact
        ``work`` (#142).
        """
        if protocol not in ContactMethod.SUPPORTED_PROTOCOLS:
            return None
        if not isinstance(name, str) or not _CONTACT_NAME.fullmatch(name):
            return None
        return f"contacts.{protocol}.{name}"

    async def create_contact_method(
        self,
        protocol: str,
        name: str,
        details: dict[str, Any],
        preference: int = 0,
    ) -> None:
        if protocol not in ContactMethod.SUPPORTED_PROTOCOLS:
            raise InteractionError(f"Unsupported contact protocol: {protocol!r}")
        path = self._path(protocol, name)
        if path is None:
            raise InteractionError(
                f"Invalid contact name {name!r}: use 1-64 letters, digits, spaces, '_', '-', '@' or '+'."
            )
        entry = {**details, "preference": preference}
        self._store().set(path, entry)

    async def get_contact_method(self, protocol: str, name: str) -> ContactMethod | None:
        path = self._path(protocol, name)
        if path is None:
            return None
        entry = get_path(self._store(), path)
        if entry is None:
            return None
        return ContactMethod(protocol=protocol, name=name, details=entry)

    async def update_contact_method(
        self,
        protocol: str,
        name: str,
        details: dict[str, Any] | None = None,
        preference: int | None = None,
        **fields: Any,
    ) -> None:
        """Update a contact method.

        ``details`` replaces the stored fields (the preference is kept unless
        ``preference`` is given); ``fields`` set individual fields. Contacts are
        stored flat, so ``details`` used to be merged in as a nested
        ``"details"`` key while the old fields stayed in use (#137).

        A secret field given as the read-path mask (``***``) keeps its stored
        value, so a contact read and written back unchanged keeps its secrets.
        """
        store = self._store()
        path = self._path(protocol, name)
        entry = get_path(store, path) if path else None
        if entry is None:
            raise ContactNotFoundError(f"Contact method {protocol!r}/{name!r} not found.")
        secret = SECRET_FIELDS.get(protocol, frozenset())
        if details is not None:
            replaced = {k: (_unmask(v, entry.get(k)) if k in secret else v) for k, v in details.items()}
            entry = {**replaced, "preference": entry.get("preference", 0)}
        for key, value in fields.items():
            entry[key] = _unmask(value, entry.get(key)) if key in secret else value
        if preference is not None:
            entry["preference"] = preference
        store.set(path, entry)

    async def delete_contact_method(self, protocol: str, name: str) -> None:
        path = self._path(protocol, name)
        if path is not None:
            self._store().delete(path)

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
        if protocol not in ContactMethod.SUPPORTED_PROTOCOLS:
            return {}
        entries = get_path(self._store(), f"contacts.{protocol}") or {}
        return {k: v for k, v in entries.items() if isinstance(v, dict)}

    # ------------------------------------------------------------------ #
    # Preferred channel                                                    #
    # ------------------------------------------------------------------ #

    async def identify_contact_method(self, topic: str | None = None) -> ContactMethod | None:
        """Pick a contact method, optionally scoped to a project/topic.

        ``topic`` looks up ``availability.by_topic.<topic>`` overrides
        (``working_hours``, ``preferred_channel``, ``out_of_office``) layered
        on top of the general ``availability.*`` settings.

        With no registered methods, falls back to the console (``stdio``) when
        there is one. Returns ``None`` when nothing can reach the user: no
        console and no method that does not need one.
        """
        # Recorded-only protocols (sms, messaging, ...) cannot carry a question,
        # so they are never candidates (#129).
        methods = [m for m in await self.list_contact_methods() if m.has_transport]
        if not self._console:
            methods = [m for m in methods if not m.uses_console]
        if not methods:
            if not self._console:
                return None
            return ContactMethod(protocol="stdio", name="default", details={})
        if len(methods) == 1:
            return methods[0]
        return await self._choose_contact_method(methods, topic=topic)

    def _resolve_availability(self, topic: str | None) -> dict[str, Any]:
        """Merge general ``availability.*`` metadata with a topic override, if any."""
        availability = {
            "preferred_channel": self._data_manager.get_metadata("availability.preferred_channel"),
            "working_hours": self._data_manager.get_metadata("availability.working_hours"),
            "out_of_office": bool(self._data_manager.get_metadata("availability.out_of_office")),
        }
        if topic:
            override = self._data_manager.get_metadata(f"availability.by_topic.{topic}")
            if isinstance(override, dict):
                for key in ("preferred_channel", "working_hours"):
                    if override.get(key) is not None:
                        availability[key] = override[key]
                if override.get("out_of_office") is not None:
                    availability["out_of_office"] = bool(override["out_of_office"])
        return availability

    async def _choose_contact_method(
        self, methods: list[ContactMethod], topic: str | None = None
    ) -> ContactMethod:
        """Ask an LLM to pick among several available contact methods.

        Falls back to the lowest-``preference`` method (restricted to
        asynchronous protocols when the user is out of office, if any such
        method is available) if the LLM call fails or returns a choice that
        isn't one of the options.
        """
        from blue_data_user_source.reasoning.reasoner import _llm_complete

        availability = self._resolve_availability(topic)
        preferred_channel = availability["preferred_channel"]
        working_hours = availability["working_hours"]
        out_of_office = availability["out_of_office"]

        tz_name = self._data_manager.get_metadata("identity.timezone")
        now = datetime.now(timezone.utc)
        within_hours = _is_within_working_hours(working_hours, tz_name, now)

        fallback = min(methods, key=lambda m: m.preference)
        if out_of_office:
            async_methods = [m for m in methods if m.is_async]
            if async_methods:
                fallback = min(async_methods, key=lambda m: m.preference)

        try:
            local_time_str = now.astimezone(ZoneInfo(tz_name)).strftime("%A, %Y-%m-%d %H:%M %Z") \
                if tz_name else f"{now.strftime('%A, %Y-%m-%d %H:%M')} UTC"
        except Exception:
            local_time_str = f"{now.strftime('%A, %Y-%m-%d %H:%M')} UTC"
        within_hours_str = {True: "yes", False: "no", None: "unknown"}[within_hours]

        options = "\n".join(
            f"- protocol={m.protocol!r}, name={m.name!r}, preference={m.preference}, "
            f"asynchronous={'yes' if m.is_async else 'no'} (lower preference = more favored)"
            for m in methods
        )
        prompt = (
            "Choose the best contact method to reach a user right now, from the options below.\n\n"
            f"Available contact methods:\n{options}\n\n"
            f"User's stated preferred channel (free text, may be empty or not match any option): "
            f"{preferred_channel or 'not specified'}\n"
            f"User's working hours (free text): {working_hours or 'not specified'}\n"
            f"Current time in the user's timezone: {local_time_str}\n"
            f"Currently within stated working hours: {within_hours_str}\n"
            f"User is currently out of office: {'yes' if out_of_office else 'no'}\n\n"
            "Weigh the stated preferred channel, working hours, and out-of-office status "
            "alongside each method's preference ranking. If the user is out of office or it "
            "is currently outside working hours, prefer an asynchronous method over a "
            "synchronous one when a reasonable asynchronous option exists. Pick exactly one "
            "method from the list above. "
            'Return only a JSON object: {"protocol": "<protocol>", "name": "<name>"}'
        )
        try:
            result = await _llm_complete(prompt, properties={"response_format": "json_object"})
        except LLMError:
            # Documented: on LLM failure, fall back to the lowest-preference method.
            return fallback
        if isinstance(result, dict):
            for method in methods:
                if method.protocol == result.get("protocol") and method.name == result.get("name"):
                    return method
        return fallback
