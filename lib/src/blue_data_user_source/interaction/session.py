from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from blue_data_user_source.types import InteractionError


class SessionManager:
    """Manages sessions, per-session queries, and per-query interactions.

    Records are stored as ``sessions.{session_id}`` (and nested
    ``.queries.{query_id}``, ``.queries.{query_id}.interactions.{interaction_id}``)
    in the dotted-path JSONSource returned by ``UserDataManager.get_session_source()``
    — same convention as ``ContactManager``.

    Resolved interaction transcripts are additionally ingested into a
    per-session ``DocumentDataSource`` via ``UserDataManager.ensure_session_doc_source``,
    for later semantic recall during query context expansion.
    """

    def __init__(self, database: str, data_manager: Any) -> None:
        self._database = database
        self._data_manager = data_manager

    def _store(self) -> Any:
        return self._data_manager.get_session_source()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ------------------------------------------------------------------ #
    # Sessions                                                             #
    # ------------------------------------------------------------------ #

    async def create_session(self) -> str:
        session_id = str(uuid4())
        self._store().set(f"sessions.{session_id}", {
            "created_at": self._now(),
            "ended_at": None,
            "status": "active",
            "doc_source_name": f"session-{session_id}",
            "queries": {},
        })
        return session_id

    async def get_session(self, session_id: str) -> dict | None:
        return self._store().get(f"sessions.{session_id}")

    async def list_sessions(self) -> dict[str, Any]:
        return self._store().get("sessions") or {}

    async def end_session(self, session_id: str) -> None:
        if await self.get_session(session_id) is None:
            raise InteractionError(f"Session {session_id!r} not found.")
        self._store().set(f"sessions.{session_id}.status", "ended")
        self._store().set(f"sessions.{session_id}.ended_at", self._now())

    # ------------------------------------------------------------------ #
    # Queries                                                              #
    # ------------------------------------------------------------------ #

    async def create_query(self, session_id: str, query: str, output_form: str = "json") -> str:
        session = await self.get_session(session_id)
        if session is None:
            raise InteractionError(f"Session {session_id!r} not found.")
        if session.get("status") == "ended":
            raise InteractionError(f"Session {session_id!r} has ended; cannot add a query to it.")
        query_id = str(uuid4())
        self._store().set(f"sessions.{session_id}.queries.{query_id}", {
            "query": query,
            "output_form": output_form,
            "created_at": self._now(),
            "interactions": {},
        })
        return query_id

    # ------------------------------------------------------------------ #
    # Interactions                                                         #
    # ------------------------------------------------------------------ #

    async def create_interaction(
        self, session_id: str, query_id: str, question: str, protocol: str, name: str,
    ) -> str:
        interaction_id = str(uuid4())
        path = f"sessions.{session_id}.queries.{query_id}.interactions.{interaction_id}"
        self._store().set(path, {
            "question": question,
            "response": None,
            "contact": {"protocol": protocol, "name": name},
            "status": "pending",
            "started_at": self._now(),
            "resolved_at": None,
        })
        return interaction_id

    async def resolve_interaction(
        self, session_id: str, query_id: str, interaction_id: str, response: str,
    ) -> None:
        path = f"sessions.{session_id}.queries.{query_id}.interactions.{interaction_id}"
        self._store().set(f"{path}.response", response)
        self._store().set(f"{path}.status", "resolved")
        self._store().set(f"{path}.resolved_at", self._now())

        question = (self._store().get(path) or {}).get("question", "")
        doc_source = self._data_manager.ensure_session_doc_source(session_id)
        doc_source.ingest_text(
            f"Q: {question}\nA: {response}",
            file_name=f"{query_id}-{interaction_id}.txt",
        )

    async def mark_interaction_timeout(
        self, session_id: str, query_id: str, interaction_id: str,
    ) -> None:
        path = f"sessions.{session_id}.queries.{query_id}.interactions.{interaction_id}"
        self._store().set(f"{path}.status", "timeout")
        self._store().set(f"{path}.resolved_at", self._now())
