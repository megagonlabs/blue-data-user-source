import io
import sys
from typing import Any

import pytest

from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.interaction.contact import ContactManager, ContactMethod
from blue_data_user_source.interaction.manager import InteractionManager
from blue_data_user_source.types import InteractionError


@pytest.fixture
async def contact_manager(
    data_manager: UserDataManager, user_id: str
) -> ContactManager:
    return ContactManager(database=user_id, data_manager=data_manager)


async def test_identify_contact_method_returns_stdio_when_no_methods_registered(
    contact_manager: ContactManager,
) -> None:
    method = await contact_manager.identify_contact_method("any query")
    assert method.protocol == "stdio"


async def test_get_contact_methods_returns_empty_list_for_new_user(
    contact_manager: ContactManager,
) -> None:
    methods = await contact_manager.get_contact_methods()
    assert methods == []


async def test_contact_method_stdio_interact_returns_interaction_manager() -> None:
    method = ContactMethod(details={}, protocol="stdio")
    mgr = method.interact()
    assert isinstance(mgr, InteractionManager)


async def test_contact_method_unsupported_protocol_raises_interaction_error() -> None:
    with pytest.raises(InteractionError, match="Unsupported contact protocol"):
        ContactMethod(details={}, protocol="carrier-pigeon")


async def test_contact_method_interact_non_stdio_raises_interaction_error() -> None:
    method = ContactMethod(details={"value": "user@example.com"}, protocol="email")
    with pytest.raises(InteractionError, match="requires a registered handler"):
        method.interact()


async def test_get_contact_methods_filtered_by_protocol(
    contact_manager: ContactManager,
) -> None:
    result = await contact_manager.get_contact_methods(protocol="email")
    assert result == []


# ── stdio interaction callbacks ───────────────────────────────────────────────

async def test_stdio_manager_start_and_stop_are_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    method = ContactMethod(details={}, protocol="stdio")
    mgr = method.interact()
    await mgr.start()
    await mgr.stop()


async def test_stdio_manager_send_writes_prompt_and_reads_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_out = io.StringIO()
    fake_in = io.StringIO("yes, remote\n")
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stdin", fake_in)

    method = ContactMethod(details={}, protocol="stdio")
    mgr = method.interact()
    response = await mgr.send("Do you prefer remote work?")

    assert response == "yes, remote"
    assert "Do you prefer remote work?" in fake_out.getvalue()


async def test_stdio_manager_send_strips_trailing_newline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stdin", io.StringIO("answer\n"))

    mgr = ContactMethod(details={}, protocol="stdio").interact()
    response = await mgr.send("question?")
    assert not response.endswith("\n")


# ── non-empty methods list ────────────────────────────────────────────────────

async def test_get_contact_methods_returns_entries_stored_in_json(
    data_manager: UserDataManager, user_id: str
) -> None:
    reg = data_manager._registries[user_id]
    await reg.set_json(
        f"{user_id}:metadata:contacts:email",
        {"type": "email", "value": "user@example.com", "preference": 1},
    )
    cm = ContactManager(database=user_id, data_manager=data_manager)
    methods = await cm.get_contact_methods()
    assert len(methods) >= 1
    assert any(m.protocol == "email" for m in methods)


async def test_identify_contact_method_picks_lowest_preference(
    data_manager: UserDataManager, user_id: str
) -> None:
    reg = data_manager._registries[user_id]
    await reg.set_json(
        f"{user_id}:contacts:a",
        {"type": "email", "value": "a@example.com", "preference": 5},
    )
    await reg.set_json(
        f"{user_id}:contacts:b",
        {"type": "sms", "value": "+1555", "preference": 1},
    )
    cm = ContactManager(database=user_id, data_manager=data_manager)
    method = await cm.identify_contact_method("any query")
    assert method.details.get("preference") == 1


async def test_get_contact_methods_filters_unsupported_protocols(
    data_manager: UserDataManager, user_id: str
) -> None:
    reg = data_manager._registries[user_id]
    await reg.set_json(
        f"{user_id}:contacts:bad",
        {"type": "carrier-pigeon", "value": "coo"},
    )
    cm = ContactManager(database=user_id, data_manager=data_manager)
    methods = await cm.get_contact_methods()
    assert all(m.protocol != "carrier-pigeon" for m in methods)


async def test_get_contact_methods_returns_empty_when_database_not_registered(
    store_factory: Any,
) -> None:
    mgr = UserDataManager(store_factory=store_factory)
    cm = ContactManager(database="never-created", data_manager=mgr)
    methods = await cm.get_contact_methods()
    assert methods == []


async def test_get_contact_methods_protocol_filter_excludes_non_matching(
    data_manager: UserDataManager, user_id: str
) -> None:
    reg = data_manager._registries[user_id]
    await reg.set_json(f"{user_id}:c:1", {"type": "email", "value": "a@b.com"})
    await reg.set_json(f"{user_id}:c:2", {"type": "sms", "value": "+1555"})

    cm = ContactManager(database=user_id, data_manager=data_manager)
    methods = await cm.get_contact_methods(protocol="email")
    assert len(methods) == 1
    assert methods[0].protocol == "email"


async def test_get_contact_methods_name_filter_excludes_non_matching(
    data_manager: UserDataManager, user_id: str
) -> None:
    reg = data_manager._registries[user_id]
    await reg.set_json(f"{user_id}:c:work", {"type": "email", "value": "w@b.com", "name": "work"})
    await reg.set_json(f"{user_id}:c:home", {"type": "email", "value": "h@b.com", "name": "home"})

    cm = ContactManager(database=user_id, data_manager=data_manager)
    methods = await cm.get_contact_methods(name="work")
    assert len(methods) == 1
    assert methods[0].details["name"] == "work"
