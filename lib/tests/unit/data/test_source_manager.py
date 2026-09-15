"""Tests for UserDataManager metadata and contact storage operations."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from blue_data_user_source.data.manager import (
    CLS_JSON_MEMORY,
    CLS_KB_MEMORY,
    UserDataManager,
    sanitize_registry_name
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
    for category in ("identity", "preferences", "availability", "privacy"):
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
# ── add_source (issue #94: names must not contain "/" or ".") ─────────────────

def test_sanitize_registry_name_strips_slash_and_dot() -> None:
    assert sanitize_registry_name("data/resume.txt") == "data__SEP__resume__SEP__txt"


def test_sanitize_registry_name_leaves_plain_names_untouched() -> None:
    assert sanitize_registry_name("resume") == "resume"


_BUILTIN_SOURCE_NAMES = {"kb", "metadata", "contacts", "sessions", "session_content", "external_documents"}


def _added_records(manager: UserDataManager) -> list[dict]:
    records = manager._registry.list_records(record_type="source", scope="/")
    return [r for r in records if r["name"] not in _BUILTIN_SOURCE_NAMES]


# ── add_source ingests via DocumentDataSource, no per-file registry entry ─────
# (issue #90; per-file registry records deliberately dropped — see #95,
# pending #89)

async def test_add_source_creates_no_per_file_registry_record(manager: UserDataManager, tmp_path: Path) -> None:
    f = tmp_path / "data" / "resume.txt"
    f.parent.mkdir()
    f.write_text("Python\n")
    await manager.add_source(f)

    assert _added_records(manager) == []
    all_names = {r["name"] for r in manager._registry.list_records(record_type="source", scope="/")}
    assert "external_documents" in all_names


async def test_add_source_with_slashy_name_creates_no_registry_record(manager: UserDataManager, tmp_path: Path) -> None:
    f = tmp_path / "resume.txt"
    f.write_text("Python\n")
    await manager.add_source(f, name="folder/resume")

    assert _added_records(manager) == []


async def test_add_source_ingests_into_external_documents_source(manager: UserDataManager, tmp_path: Path) -> None:
    f = tmp_path / "resume.txt"
    f.write_text("Python\nSQL\nMachine learning\n")
    await manager.add_source(f)

    doc_source = manager.ensure_external_documents_source()
    results = doc_source.execute_query({"op": "DOCUMENT.SEARCH", "query": "machine learning", "k": 5})
    assert len(results) > 0


async def test_add_source_ingests_even_without_queries(manager: UserDataManager, tmp_path: Path) -> None:
    """Ingestion into external_documents is unconditional — unlike the old
    FileSource path, which only ever read the file when --query was given."""
    f = tmp_path / "resume.txt"
    f.write_text("Python\nSQL\n")
    await manager.add_source(f)

    doc_source = manager.ensure_external_documents_source()
    results = doc_source.execute_query({"op": "DOCUMENT.SEARCH", "query": "Python", "k": 5})
    assert len(results) > 0


async def test_add_source_with_queries_still_imports_into_kb(manager: UserDataManager, tmp_path: Path) -> None:
    f = tmp_path / "resume.txt"
    f.write_text("Alice knows Python.\n")
    await manager.add_source(f, queries=["what skills does alice have"])

    kb = manager._ensure_kb_source()
    data = await kb.fetch_database_data(manager._database, compact=True)
    assert data


async def test_add_source_extraction_text_keeps_section_headings(
    manager: UserDataManager, tmp_path: Path
) -> None:
    """The doc pipeline lifts headings out of the chunk body into "section_title";
    a resume's job titles and degree are headings, so joining only the bodies would
    hand the extractor a document with exactly those removed."""
    f = tmp_path / "resume.txt"
    f.write_text(
        "SENIOR PROJECT MANAGER\n"
        "TechSolutions Inc., San Jose, CA\n"
        "\n"
        "SKILLS\n"
        "* Technical: SQL, Basic Python\n"
    )
    kb = manager._ensure_kb_source()
    with patch.object(kb, "import_text", AsyncMock()) as mock_import:
        await manager.add_source(f, queries=["what is the job title"], effort="low")

    text = mock_import.await_args.args[1]
    assert "SENIOR PROJECT MANAGER" in text
    assert "TechSolutions Inc." in text
    assert mock_import.await_args.kwargs["effort"] == "low"


async def test_add_source_defaults_to_medium_effort(
    manager: UserDataManager, tmp_path: Path
) -> None:
    f = tmp_path / "resume.txt"
    f.write_text("Alice knows Python.\n")
    kb = manager._ensure_kb_source()
    with patch.object(kb, "import_text", AsyncMock()) as mock_import:
        await manager.add_source(f, queries=["what skills"])

    assert mock_import.await_args.kwargs["effort"] == "medium"


async def test_add_source_names_the_owner_in_the_source_description(
    manager: UserDataManager, tmp_path: Path
) -> None:
    """The SOURCE description reaches the extraction prompt, so it is what ties an
    unattributed document to this user rather than to a newly invented person."""
    manager.set_metadata("identity.name", "Alice Chen")
    f = tmp_path / "resume.txt"
    f.write_text("Results-driven Project Manager.\n")
    await manager.add_source(f)

    sources = await manager.list_sources()
    assert any("Alice Chen" in (s.get("description") or "") for s in sources)


async def test_add_source_keeps_an_explicit_description(
    manager: UserDataManager, tmp_path: Path
) -> None:
    f = tmp_path / "resume.txt"
    f.write_text("Results-driven Project Manager.\n")
    await manager.add_source(f, description="Q3 resume draft")

    sources = await manager.list_sources()
    assert any(s.get("description") == "Q3 resume draft" for s in sources)


# ── set_person_name ──────────────────────────────────────────────────────────

async def test_set_person_name_creates_single_user_entity_labeled_with_full_name(
    manager: UserDataManager,
) -> None:
    await manager.set_person_name("Alice", "Smith")

    kb = manager._ensure_kb_source()
    data = await kb.fetch_database_data(manager._database, compact=False)
    entities = [n for n in data["nodes"] if n["label"] == "ENTITY"]
    assert len(entities) == 1
    assert entities[0]["properties"]["name"] == "Alice Smith"

    user_class = await kb.find_class(manager._database, "USER")
    is_instance_edges = [
        e for e in data["edges"]
        if e["type"] == "IS_INSTANCE_OF" and e["source_id"] == entities[0]["id"]
    ]
    assert [e["target_id"] for e in is_instance_edges] == [user_class["id"]]

    literals = {n["id"]: n["properties"] for n in data["nodes"] if n["label"] == "LITERAL"}
    has_property_edges = [
        e for e in data["edges"]
        if e["type"] == "HAS_PROPERTY" and e["source_id"] == entities[0]["id"]
    ]
    values = {literals[e["target_id"]]["value"] for e in has_property_edges}
    assert values == {"Alice", "Smith"}


async def test_set_person_name_without_last_name_only_sets_first_name_property(
    manager: UserDataManager,
) -> None:
    await manager.set_person_name("Cher")

    kb = manager._ensure_kb_source()
    data = await kb.fetch_database_data(manager._database, compact=False)
    entities = [n for n in data["nodes"] if n["label"] == "ENTITY"]
    assert len(entities) == 1

    literals = {n["id"]: n["properties"] for n in data["nodes"] if n["label"] == "LITERAL"}
    has_property_edges = [
        e for e in data["edges"]
        if e["type"] == "HAS_PROPERTY" and e["source_id"] == entities[0]["id"]
    ]
    values = {literals[e["target_id"]]["value"] for e in has_property_edges}
    assert values == {"Cher"}


async def test_set_person_name_is_idempotent_for_same_first_name(manager: UserDataManager) -> None:
    """Calling twice with the same first name reuses the entity instead of duplicating it."""
    first_id = await manager.set_person_name("Alice", "Smith")
    second_id = await manager.set_person_name("Alice", "Smith")
    assert first_id == second_id

    kb = manager._ensure_kb_source()
    data = await kb.fetch_database_data(manager._database, compact=False)
    entities = [n for n in data["nodes"] if n["label"] == "ENTITY"]
    assert len(entities) == 1


# ── seed_user_entity (default self-entity on create/reset) ────────────────────

async def test_build_seeds_default_user_entity(manager: UserDataManager) -> None:
    """A fresh database already has a self-entity: <database> -> IS_INSTANCE_OF -> USER,
    with USER -> IS_SUBCLASS_OF -> PERSON coming from the base schema."""
    kb = manager._ensure_kb_source()
    entity = await kb.find_entity(manager._database, manager._database)
    assert entity is not None

    user_class = await kb.find_class(manager._database, "USER")
    data = await kb.fetch_database_data(manager._database, compact=False)
    is_instance_edges = [
        e for e in data["edges"]
        if e["type"] == "IS_INSTANCE_OF" and e["source_id"] == entity["id"]
    ]
    assert [e["target_id"] for e in is_instance_edges] == [user_class["id"]]

    schema = await kb.export_database_schema(manager._database)
    subclass_pairs = {
        (rel["source"], rel["target"])
        for rel in schema["relations"].values()
        if rel.get("name") == "IS_SUBCLASS_OF"
    }
    assert ("USER", "PERSON") in subclass_pairs


# ── seed_kb_source_schema (subclass hierarchy) ────────────────────────────────

async def test_seed_schema_resolves_subclass_endpoints_by_exact_name() -> None:
    """Subclass endpoints resolve by exact name, not by ranked search. With a search
    index enabled, searching "PERSON" scores USER ("Digital user profile extending
    PERSON") and EMPLOYEE ("Person employed by an organization") above PERSON
    itself — taking the top hit seeds USER IS_SUBCLASS_OF USER."""
    mgr = UserDataManager("bm25db", _MEM_JSON)
    await mgr.build(
        schema_path=_SCHEMA,
        kb_source_props={**_MEM_KB, "search": {"mode": "bm25"}},
        metadata_schema_path=None,
        metadata_source_props=_MEM_JSON,
        contact_schema_path=None,
        contact_source_props=_MEM_JSON,
        session_source_props=_MEM_JSON,
    )
    kb = mgr._ensure_kb_source()
    assert kb._search_indexer is not None, "test is meaningless without a ranked index"

    schema = await kb.export_database_schema(mgr._database)
    pairs = {
        (rel["source"], rel["target"])
        for rel in schema["relations"].values()
        if rel.get("name") == "IS_SUBCLASS_OF"
    }
    assert pairs == {
        ("USER", "PERSON"),
        ("EMPLOYEE", "PERSON"),
        ("COMPANY", "ORGANIZATION"),
        ("CITY", "LOCATION"),
        ("COUNTRY", "LOCATION"),
    }


async def test_worked_at_accepts_the_users_own_entity_as_head(manager: UserDataManager) -> None:
    """WORKED_AT's domain is PERSON, not EMPLOYEE: nothing in the pipeline ever
    classifies anyone as an EMPLOYEE, so an EMPLOYEE domain made employment facts
    unwritable. Relies on USER IS_SUBCLASS_OF PERSON for the domain check to pass."""
    kb = manager._ensure_kb_source()
    alice_id = await manager.set_person_name("Alice", "Chen")   # instance of USER
    company_class = await kb.find_class(manager._database, "COMPANY")
    employer_id = await kb.add_entity(
        manager._database, "TechSolutions Inc.", class_id=company_class["id"]
    )
    worked_at = await kb.find_relation_type(manager._database, "WORKED_AT")

    verdict = await kb.is_fact_allowed(
        manager._database, alice_id, worked_at["id"], employer_id
    )
    assert verdict["ok"], verdict


async def test_worked_at_carries_a_job_title(manager: UserDataManager) -> None:
    """A resume's job titles are only extractable if the schema can hold one; with no
    JOB_TITLE class, TITLE on WORKED_AT is where "most recent job title" lives."""
    kb = manager._ensure_kb_source()
    alice_id = await manager.set_person_name("Alice", "Chen")
    company_class = await kb.find_class(manager._database, "COMPANY")
    employer_id = await kb.add_entity(
        manager._database, "TechSolutions Inc.", class_id=company_class["id"]
    )
    worked_at = await kb.find_relation_type(manager._database, "WORKED_AT")
    fact_id = await kb.add_fact(
        manager._database, head_entity_id=alice_id, tail_entity_id=employer_id,
        relation_id=worked_at["id"],
    )

    title = await kb.find_property(manager._database, "TITLE")
    assert title is not None, "TITLE must be declared on WORKED_AT"
    verdict = await kb.is_property_allowed(manager._database, fact_id, title["id"])
    assert verdict["ok"], verdict

    await kb.add_fact_property_value(
        manager._database, "Senior Project Manager",
        fact_id=fact_id, property_id=title["id"],
    )
    rows = await kb.fetch_database_data(manager._database, compact=True)
    assert any(
        r.get("relation_type") == "IS_VALUE_OF"
        and r.get("property_name") == "TITLE"
        and r.get("property_value") == "Senior Project Manager"
        for r in rows
    )


async def test_set_person_name_renames_seeded_placeholder_entity(manager: UserDataManager) -> None:
    """set_person_name reuses the placeholder seeded by build(), rather than creating
    a second entity alongside it."""
    kb = manager._ensure_kb_source()
    placeholder = await kb.find_entity(manager._database, manager._database)

    entity_id = await manager.set_person_name("Alice", "Smith")
    assert entity_id == placeholder["id"]

    data = await kb.fetch_database_data(manager._database, compact=False)
    entities = [n for n in data["nodes"] if n["label"] == "ENTITY"]
    assert len(entities) == 1
    assert entities[0]["properties"]["name"] == "Alice Smith"


async def test_reset_reseeds_default_user_entity(manager: UserDataManager) -> None:
    await manager.set_person_name("Alice", "Smith")
    await manager.reset(schema_path=_SCHEMA, sources={"kb"})

    kb = manager._ensure_kb_source()
    data = await kb.fetch_database_data(manager._database, compact=False)
    entities = [n for n in data["nodes"] if n["label"] == "ENTITY"]
    assert len(entities) == 1
    assert entities[0]["properties"]["name"] == manager._database
