"""Tests for UserDataManager metadata and contact storage operations."""
from __future__ import annotations

import pytest

from blue_data_user_source.data.manager import UserDataManager


# ── metadata ──────────────────────────────────────────────────────────────────

async def test_set_and_get_metadata(manager: UserDataManager) -> None:
    manager.set_metadata("identity.name", "Alice")
    assert manager.get_metadata("identity.name") == "Alice"


async def test_get_metadata_unknown_key_returns_none(manager: UserDataManager) -> None:
    assert manager.get_metadata("identity.nonexistent") is None


async def test_delete_metadata(manager: UserDataManager) -> None:
    manager.set_metadata("identity.name", "Alice")
    manager.delete_metadata("identity.name")
    assert manager.get_metadata("identity.name") is None


async def test_list_metadata_contains_all_schema_categories(manager: UserDataManager) -> None:
    meta = manager.list_metadata()
    for category in ("identity", "preferences", "policy", "credentials", "skills", "availability", "instructions"):
        assert category in meta


async def test_seed_metadata_schema_initializes_keys_to_none(manager: UserDataManager) -> None:
    # schema seeds identity.name as null by default
    assert manager.get_metadata("identity.name") is None


async def test_set_metadata_overwrites_existing_value(manager: UserDataManager) -> None:
    manager.set_metadata("preferences.language", "English")
    manager.set_metadata("preferences.language", "Turkish")
    assert manager.get_metadata("preferences.language") == "Turkish"


async def test_list_metadata_reflects_set_values(manager: UserDataManager) -> None:
    manager.set_metadata("identity.name", "Bob")
    meta = manager.list_metadata()
    assert meta["identity"]["name"] == "Bob"


# ── contact storage (via manager helpers) ─────────────────────────────────────

async def test_get_contact_returns_none_for_missing(manager: UserDataManager) -> None:
    assert manager.get_contact("email", "work") is None


async def test_set_and_get_contact_field(manager: UserDataManager) -> None:
    manager.set_contact_field("email", "work", "address", "alice@example.com")
    entry = manager.get_contact("email", "work")
    assert entry is not None
    assert entry["address"] == "alice@example.com"


async def test_delete_contact_removes_entry(manager: UserDataManager) -> None:
    manager.set_contact_field("email", "work", "address", "alice@example.com")
    manager.delete_contact("email", "work")
    assert manager.get_contact("email", "work") is None


async def test_get_contacts_returns_all_protocols(manager: UserDataManager) -> None:
    contacts = manager.get_contacts()
    # contact schema seeds top-level protocol buckets
    assert isinstance(contacts, dict)
    assert "email" in contacts
