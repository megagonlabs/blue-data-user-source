"""When the user cannot be reached, the query still answers and the record says why (#138).

Building the channel, starting it and sending all used to run outside the
error handling: a misconfigured contact or a down endpoint failed the whole
query, threw away the retrieved data, and left the interaction ``pending``.
"""
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.interaction.contact import ContactManager, ContactMethod
from blue_data_user_source.interaction.session import SessionManager
from blue_data_user_source.reasoning.metric import MetricEvaluation
from blue_data_user_source.reasoning.reasoner import UserQueryReasoner
from blue_data_user_source.types import InteractionError

_FAILING = [MetricEvaluation(name="completeness", score=0.0, reasoning="", passes=False)]
_WEBHOOK = {"url": "https://hooks.example.com/q", "response_base_url": "http://localhost:8000", "timeout": 0.05}


class _ConnectError(Exception):
    """Stands in for httpx.HTTPError."""


async def _ask(manager: UserDataManager) -> list:
    reasoner = UserQueryReasoner(source=MagicMock(console=False, replies=None), manager=manager)
    reasoner.assess_query_results = AsyncMock(return_value=_FAILING)  # type: ignore[method-assign]
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(return_value="Where do you live?")):
        return await reasoner.resolve_via_interaction("where do I live?", "where?", ["Berlin"], {}, max_rounds=3)


async def _interactions(manager: UserDataManager, user_id: str) -> list[dict]:
    sessions = await SessionManager(database=user_id, data_manager=manager).list_sessions()
    return [ia for s in sessions.values() for q in s["queries"].values() for ia in q["interactions"].values()]


async def test_a_contact_missing_a_required_field_fails_cleanly(manager: UserDataManager, user_id: str) -> None:
    # What `blue-userdb contact add email work` creates before its fields are set.
    await ContactManager(user_id, manager).create_contact_method("email", "work", {})

    assert await _ask(manager) == []  # the query goes on; no answer was collected

    [record] = await _interactions(manager, user_id)
    assert record["status"] == "failed"
    assert "missing required field 'address'" in record["error"]
    assert record["resolved_at"]


async def test_a_webhook_that_is_down_fails_cleanly(manager: UserDataManager, user_id: str) -> None:
    await ContactManager(user_id, manager).create_contact_method("webhook", "bot", _WEBHOOK)
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(side_effect=_ConnectError("All connection attempts failed"))
    httpx = MagicMock(AsyncClient=MagicMock(return_value=client), HTTPError=_ConnectError)

    with patch.dict(sys.modules, {"httpx": httpx}):
        assert await _ask(manager) == []

    [record] = await _interactions(manager, user_id)
    assert record["status"] == "failed"
    assert "could not deliver the question" in record["error"]
    assert "All connection attempts failed" in record["error"]


async def test_no_answer_in_time_ends_timeout_and_the_query_still_answers(
    manager: UserDataManager, user_id: str,
) -> None:
    await ContactManager(user_id, manager).create_contact_method("webhook", "bot", _WEBHOOK)
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=MagicMock(raise_for_status=MagicMock()))  # delivered, never answered
    httpx = MagicMock(AsyncClient=MagicMock(return_value=client), HTTPError=_ConnectError)

    with patch.dict(sys.modules, {"httpx": httpx}):
        assert await _ask(manager) == []

    [record] = await _interactions(manager, user_id)
    assert record["status"] == "timeout"


async def test_onboarding_records_a_failed_question_and_moves_on(manager: UserDataManager, user_id: str) -> None:
    await ContactManager(user_id, manager).create_contact_method("email", "work", {})
    reasoner = UserQueryReasoner(source=MagicMock(console=False, replies=None), manager=manager)
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(return_value={})):
        await reasoner.onboard(metadata_schema_path=None, include_metadata=False)  # asks the name question

    records = await _interactions(manager, user_id)
    assert records and all(r["status"] == "failed" for r in records)
    assert manager.get_metadata("identity.name") is None


# ── a malformed contact (#202) ────────────────────────────────────────────────

@pytest.mark.parametrize(("protocol", "details", "reason"), [
    ("webhook", {**_WEBHOOK, "timeout": "soon"}, "timeout"),
    ("email", {"address": "a@example.com", "from_address": "b@example.com", "smtp_host": "smtp",
               "reply_domain": "example.com", "response_base_url": "http://x", "smtp_port": "smtp"}, "smtp_port"),
    ("webhook", {**_WEBHOOK, "response_base_url": 5}, "malformed"),  # stored before writes were checked
])
async def test_a_malformed_contact_ends_failed_and_the_query_still_answers(
    manager: UserDataManager, user_id: str, protocol: str, details: dict, reason: str,
) -> None:
    manager._ensure_contact_source().set(f"contacts.{protocol}.bad", details)
    assert await _ask(manager) == []
    [record] = await _interactions(manager, user_id)
    assert record["status"] == "failed"
    assert reason in record["error"]


def test_an_email_contact_for_the_console_needs_an_address() -> None:
    method = ContactMethod("email", "dev", {"inbound_provider": "stdio"})
    with pytest.raises(InteractionError, match="address"):
        method.interact()


async def test_a_stored_preference_that_is_no_number_does_not_stop_the_choice(
    manager: UserDataManager, user_id: str,
) -> None:
    manager._ensure_contact_source().set("contacts.webhook.bad", {**_WEBHOOK, "preference": "high"})
    cm = ContactManager(user_id, manager)
    assert (await cm.identify_contact_method()).preference == 0

