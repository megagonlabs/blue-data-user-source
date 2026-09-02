"""Tests for UserDataManager metadata and contact storage operations."""
from __future__ import annotations

from pathlib import Path

import pytest

from blue_data_user_source.data.manager import UserDataManager, sanitize_registry_name
from blue_data_user_source.sources.file import FileSource


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


# ── add_source (issue #94: names must not contain "/" or ".") ─────────────────

def test_sanitize_registry_name_strips_slash_and_dot() -> None:
    assert sanitize_registry_name("data/resume.txt") == "data__SEP__resume__SEP__txt"


def test_sanitize_registry_name_leaves_plain_names_untouched() -> None:
    assert sanitize_registry_name("resume") == "resume"


def _added_records(manager: UserDataManager) -> list[dict]:
    records = manager._registry.list_records(record_type="source", scope="/")
    return [r for r in records if r["name"] not in {"kb", "metadata", "contacts", "sessions"}]


async def test_add_source_default_name_has_no_slash(manager: UserDataManager, tmp_path: Path) -> None:
    f = tmp_path / "data" / "resume.txt"
    f.parent.mkdir()
    f.write_text("Python\n")
    await manager.add_source(FileSource(f))

    records = _added_records(manager)
    assert len(records) == 1
    assert "/" not in records[0]["name"]
    assert "." not in records[0]["name"]


async def test_add_source_registers_absolute_path(manager: UserDataManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "data" / "resume.txt"
    f.parent.mkdir()
    f.write_text("Python\n")
    await manager.add_source(FileSource(Path("data/resume.txt")))

    records = _added_records(manager)
    assert len(records) == 1
    stored_path = records[0]["properties"]["connection"]["path"]
    assert Path(stored_path).is_absolute()
    assert Path(stored_path) == f.resolve()


async def test_add_source_explicit_name_with_slash_is_sanitized(manager: UserDataManager, tmp_path: Path) -> None:
    f = tmp_path / "resume.txt"
    f.write_text("Python\n")
    await manager.add_source(FileSource(f), name="folder/resume")

    records = _added_records(manager)
    assert records[0]["name"] == "folder__SEP__resume"
