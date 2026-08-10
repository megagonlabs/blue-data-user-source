"""Tests for ContactMethod and ContactManager."""
from __future__ import annotations

import io
import sys

import pytest

from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.interaction.contact import ContactManager, ContactMethod
from blue_data_user_source.interaction.manager import InteractionManager
from blue_data_user_source.types import InteractionError


@pytest.fixture
def contact_manager(manager: UserDataManager, user_id: str) -> ContactManager:
    return ContactManager(database=user_id, data_manager=manager)


# ── ContactMethod ─────────────────────────────────────────────────────────────

def test_contact_method_unsupported_protocol_raises() -> None:
    with pytest.raises(InteractionError, match="Unsupported contact protocol"):
        ContactMethod(protocol="carrier-pigeon", name="x", details={})


def test_contact_method_stdio_interact_returns_interaction_manager() -> None:
    method = ContactMethod(protocol="stdio", name="default", details={})
    assert isinstance(method.interact(), InteractionManager)


def test_contact_method_non_stdio_interact_raises() -> None:
    method = ContactMethod(protocol="email", name="work", details={"address": "a@b.com"})
    with pytest.raises(InteractionError, match="requires a registered handler"):
        method.interact()


def test_contact_method_preference_defaults_to_zero() -> None:
    method = ContactMethod(protocol="stdio", name="default", details={})
    assert method.preference == 0


def test_contact_method_preference_from_details() -> None:
    method = ContactMethod(protocol="email", name="work", details={"preference": 3})
    assert method.preference == 3


# ── ContactManager CRUD ───────────────────────────────────────────────────────

async def test_list_contact_methods_empty_for_new_user(contact_manager: ContactManager) -> None:
    methods = await contact_manager.list_contact_methods()
    assert methods == []


async def test_create_and_get_contact_method(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {"address": "alice@example.com"})
    method = await contact_manager.get_contact_method("email", "work")
    assert method is not None
    assert method.protocol == "email"
    assert method.name == "work"
    assert method.details["address"] == "alice@example.com"


async def test_get_missing_contact_method_returns_none(contact_manager: ContactManager) -> None:
    result = await contact_manager.get_contact_method("email", "nonexistent")
    assert result is None


async def test_delete_contact_method(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {"address": "alice@example.com"})
    await contact_manager.delete_contact_method("email", "work")
    assert await contact_manager.get_contact_method("email", "work") is None


async def test_update_contact_method(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {"address": "old@example.com"})
    await contact_manager.update_contact_method("email", "work", address="new@example.com")
    method = await contact_manager.get_contact_method("email", "work")
    assert method is not None
    assert method.details["address"] == "new@example.com"


async def test_update_missing_contact_method_raises(contact_manager: ContactManager) -> None:
    with pytest.raises(InteractionError, match="not found"):
        await contact_manager.update_contact_method("email", "ghost", address="x@y.com")


async def test_create_unsupported_protocol_raises(contact_manager: ContactManager) -> None:
    with pytest.raises(InteractionError, match="Unsupported contact protocol"):
        await contact_manager.create_contact_method("carrier-pigeon", "x", {})


# ── list / filter ─────────────────────────────────────────────────────────────

async def test_list_contact_methods_returns_created_entry(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {"address": "a@b.com"})
    methods = await contact_manager.list_contact_methods()
    assert any(m.protocol == "email" and m.name == "work" for m in methods)


async def test_list_contact_methods_filtered_by_protocol(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {})
    await contact_manager.create_contact_method("sms", "mobile", {"number": "+1555"})
    methods = await contact_manager.list_contact_methods(protocol="email")
    assert len(methods) == 1
    assert methods[0].protocol == "email"


async def test_list_protocols(contact_manager: ContactManager) -> None:
    protocols = await contact_manager.list_protocols()
    # contact schema seeds all protocol buckets
    assert "email" in protocols
    assert "sms" in protocols


async def test_list_named_entries(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {"address": "a@b.com"})
    await contact_manager.create_contact_method("email", "home", {"address": "h@b.com"})
    entries = await contact_manager.list_named_entries("email")
    assert "work" in entries
    assert "home" in entries


# ── identify_contact_method ───────────────────────────────────────────────────

async def test_identify_returns_stdio_when_no_methods(contact_manager: ContactManager) -> None:
    method = await contact_manager.identify_contact_method()
    assert method.protocol == "stdio"


async def test_identify_picks_lowest_preference(contact_manager: ContactManager) -> None:
    await contact_manager.create_contact_method("email", "work", {}, preference=5)
    await contact_manager.create_contact_method("sms", "mobile", {}, preference=1)
    method = await contact_manager.identify_contact_method()
    assert method.protocol == "sms"
    assert method.preference == 1


# ── stdio interaction ─────────────────────────────────────────────────────────

async def test_stdio_send_writes_prompt_and_reads_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_out = io.StringIO()
    fake_in = io.StringIO("yes, remote\n")
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stdin", fake_in)

    method = ContactMethod(protocol="stdio", name="default", details={})
    mgr = method.interact()
    response = await mgr.send("Do you prefer remote work?")

    assert response == "yes, remote"
    assert "Do you prefer remote work?" in fake_out.getvalue()


async def test_stdio_send_strips_trailing_newline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stdin", io.StringIO("answer\n"))

    mgr = ContactMethod(protocol="stdio", name="default", details={}).interact()
    assert not (await mgr.send("q?")).endswith("\n")
