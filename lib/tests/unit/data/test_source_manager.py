"""Tests for UserDataManager metadata and contact storage operations."""
from __future__ import annotations

from pathlib import Path

import pytest

from blue_data_user_source.data.manager import (
    CLS_JSON_MEMORY,
    CLS_KB_MEMORY,
    UserDataManager,
)

_SCHEMA = str(Path(__file__).parent.parent.parent.parent / "src" / "blue_data_user_source" / "data" / "schema.json")
_MEM_JSON = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}


async def _build_file_backed_manager(tmp_path: Path, user_id: str, directory: Path) -> UserDataManager:
    mgr = UserDataManager(
        user_id, _MEM_JSON,
        doc_source_props={
            "embedding_model": "dummy",
            "vector_source": {"backend": "file", "directory": str(directory)},
        },
    )
    await mgr.build(
        schema_path=_SCHEMA,
        kb_source_props=_MEM_KB,
        metadata_schema_path=None,
        metadata_source_props=_MEM_JSON,
        contact_schema_path=None,
        contact_source_props=_MEM_JSON,
        session_source_props=_MEM_JSON,
    )
    return mgr


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


# ── session content cleanup (regression test for #93) ─────────────────────────

async def test_reset_removes_session_transcripts_and_vector_store(
    tmp_path: Path, user_id: str,
) -> None:
    directory = tmp_path / "sessions"
    mgr = await _build_file_backed_manager(tmp_path, user_id, directory)

    session_id = "session-1"
    mgr.save_session_transcript(session_id, "q1-i1.txt", "sure, blue")
    mgr.ensure_session_doc_source(session_id).ingest_text("sure, blue", file_name="q1-i1.txt")

    transcript_path = directory / "transcripts" / session_id / "q1-i1.txt"
    documents_path = directory / "documents.json"
    assert transcript_path.is_file()
    assert documents_path.is_file()

    await mgr.reset(sources={"sessions"})

    assert not transcript_path.exists()
    assert not (directory / "transcripts").exists()
    assert not documents_path.exists()


async def test_destroy_removes_session_content_directory(
    tmp_path: Path, user_id: str,
) -> None:
    directory = tmp_path / "sessions"
    mgr = await _build_file_backed_manager(tmp_path, user_id, directory)

    session_id = "session-1"
    mgr.save_session_transcript(session_id, "q1-i1.txt", "sure, blue")
    mgr.ensure_session_doc_source(session_id).ingest_text("sure, blue", file_name="q1-i1.txt")

    assert directory.exists()

    mgr.destroy()

    assert not directory.exists()
