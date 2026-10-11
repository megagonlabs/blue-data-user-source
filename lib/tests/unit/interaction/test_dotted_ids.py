"""Identifiers that are dot-path segments cannot address other records (#142).

Session ids and contact names are interpolated into dot-notation store paths:
"<sid>.queries.<qid>" read and ended a query record as if it were a session,
and a contact named "work.address" overwrote contact work's address.
(User names are validated since #146; see test_user_names.py.)
"""
from __future__ import annotations

import pytest

from blue_data_user_source import SessionNotFoundError
from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.interaction.contact import ContactManager
from blue_data_user_source.interaction.session import SessionManager
from blue_data_user_source.types import InteractionError


async def test_a_dotted_session_id_is_unknown_and_changes_nothing(manager: UserDataManager, user_id: str) -> None:
    sm = SessionManager(database=user_id, data_manager=manager)
    sid = await sm.create_session()
    qid = await sm.create_query(sid, "q1")
    crafted = f"{sid}.queries.{qid}"

    assert await sm.get_session(crafted) is None
    with pytest.raises(SessionNotFoundError):
        await sm.end_session(crafted)
    with pytest.raises(SessionNotFoundError):
        await sm.create_query(crafted, "q2")

    session = await sm.get_session(sid)
    assert session["status"] == "active"
    assert set(session["queries"][qid]) == {"query", "created_at", "output_form", "interactions"}


@pytest.mark.parametrize("name", ["work.address", "", "a" * 65, "x[0]", "*"])
async def test_a_contact_name_that_is_not_one_segment_is_refused(
    manager: UserDataManager, user_id: str, name: str,
) -> None:
    cm = ContactManager(user_id, manager)
    await cm.create_contact_method("email", "work", {"address": "a@example.com"})

    with pytest.raises(InteractionError, match="Invalid contact name"):
        await cm.create_contact_method("email", name, {"address": "other@example.com"})
    with pytest.raises(InteractionError, match="Invalid contact"):
        manager.set_contact_field("email", name, "address", "other@example.com")
    assert await cm.get_contact_method("email", name) is None
    assert manager.get_contact("email", name) is None
    await cm.delete_contact_method("email", name)
    manager.delete_contact("email", name)

    assert (await cm.get_contact_method("email", "work")).details == {"address": "a@example.com", "preference": 0}


async def test_ordinary_contact_names_still_work(manager: UserDataManager, user_id: str) -> None:
    cm = ContactManager(user_id, manager)
    for name in ("work", "slack-bot", "Work email", "a_b", "me+alerts@home"):
        await cm.create_contact_method("email", name, {"address": "a@example.com"})
        assert await cm.get_contact_method("email", name) is not None
