"""Delete and reset remove files only inside the user data directory (#156).

A store's recorded path may come from another tool, an older version or a shared
registry, so a path outside the data directory, or one that leaves it through a
symlink, is refused (logged, and returned to the caller) rather than deleted.
Each path is checked with blue-data's ``contain()``.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from blue_data_user_source import FileUserSource, MemoryUserSource, UserExistsError, UserSource
from blue_data_user_source.data.manager import CLS_JSON_FILE, CLS_KB_MEMORY

_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}


def _json_file(path: Path) -> dict:
    return {"_class": CLS_JSON_FILE, "connection": {"protocol": "json/file", "path": str(path)}}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    victim_dir = tmp_path / "elsewhere"
    victim_dir.mkdir()
    return victim_dir


def _source(data_dir: Path) -> FileUserSource:
    return FileUserSource("u", {"connection": {"path": str(data_dir / "registry.json")}})


def test_a_normal_delete_still_removes_everything(data_dir: Path) -> None:
    us = _source(data_dir)
    us.create_database("alice")
    us.set_metadata("alice", "identity.name", "Alice")
    assert asyncio.run(us.delete_user("alice")) == []
    assert not (data_dir / "registries" / "alice.json").exists()
    assert not list((data_dir / "sources").glob("alice/*.json"))


def test_delete_leaves_no_directory_or_lock_file_behind(data_dir: Path, tmp_path: Path) -> None:
    """The stores' ``*.lock`` sidecars go too, and with them the user's directory (#179)."""
    resume = tmp_path / "resume.txt"
    resume.write_text("Ivan has worked as a data engineer since 2019.")
    us = _source(data_dir)
    us.create_database("ivan")
    us.set_metadata("ivan", "identity.name", "Ivan")
    asyncio.run(us.add_contact_method("ivan", "email", "work", {"address": "i@example.com"}))
    asyncio.run(us.create_session("ivan"))
    asyncio.run(us.add_source(str(resume), database="ivan"))
    assert list(data_dir.rglob("*.lock"))

    assert asyncio.run(us.delete_user("ivan")) == []

    assert [str(p.relative_to(data_dir)) for p in data_dir.rglob("*") if "ivan" in str(p)] == []


def test_a_recorded_path_outside_the_data_directory_is_kept(
    data_dir: Path, outside: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    victim = outside / "metadata.json"
    us = _source(data_dir)
    # A record as another tool might have written it: the metadata store points elsewhere.
    us.create_database("bob", {"metadata_source": _json_file(victim)})
    us.set_metadata("bob", "identity.name", "Bob")
    assert victim.exists()

    with caplog.at_level(logging.WARNING):
        refused = asyncio.run(us.delete_user("bob"))

    assert victim.exists()
    assert refused == [str(victim)]
    assert "outside the data directory" in caplog.text
    assert not (data_dir / "registries" / "bob.json").exists()  # what is inside still goes
    assert "bob" not in us.list_users()


def test_a_symlink_out_of_the_data_directory_is_refused(data_dir: Path, outside: Path) -> None:
    victim = outside / "contacts.json"
    data_dir.mkdir(parents=True)
    (data_dir / "link").symlink_to(outside, target_is_directory=True)
    us = _source(data_dir)
    us.create_database("carol", {"contact_source": _json_file(data_dir / "link" / "contacts.json")})
    asyncio.run(us.add_contact_method("carol", "email", "work", {"address": "c@example.com"}))
    assert victim.exists()

    refused = asyncio.run(us.delete_user("carol"))

    assert victim.exists()
    assert refused == [str(data_dir / "link" / "contacts.json")]


def test_reset_keeps_a_document_store_recorded_outside(data_dir: Path, outside: Path) -> None:
    sessions_dir = outside / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "documents.json").write_text("{}")
    (outside / "external_documents").mkdir()
    (outside / "external_documents" / "keep.json").write_text("{}")
    us = _source(data_dir)
    us.create_database("dan", {
        "doc_source": {"embedding_model": "dummy",
                       "vector_source": {"backend": "file", "directory": str(sessions_dir)}},
    })

    refused = asyncio.run(us.reset_user("dan"))

    assert (sessions_dir / "documents.json").exists()
    assert (outside / "external_documents" / "keep.json").exists()
    assert str(sessions_dir) in refused and str(outside / "external_documents") in refused


def test_a_source_without_a_data_directory_deletes_no_files(tmp_path: Path) -> None:
    victim = tmp_path / "metadata.json"
    us = MemoryUserSource("u")
    us.create_database("erin", {"metadata_source": _json_file(victim)})
    us.set_metadata("erin", "identity.name", "Erin")

    assert asyncio.run(us.delete_user("erin")) == [str(victim)]
    assert victim.exists()


def test_the_file_layout_is_composed_with_contain(data_dir: Path) -> None:
    """A symlinked data directory resolves; the composed paths stay inside it."""
    real = data_dir.parent / "real"
    real.mkdir(parents=True)
    data_dir.symlink_to(real, target_is_directory=True)
    props = _source(data_dir).default_user_props("frank")
    assert Path(props["registry"]["connection"]["path"]) == real / "registries" / "frank.json"
    assert Path(props["kb_source"]["connection"]["directory"]) == real / "sources" / "frank"


# ── "~/…" store paths (#171) ─────────────────────────────────────────────────

_KB_FILE = "blue_data_kb_source.file_kb_source.FileKBSource"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir, cwd = tmp_path / "home", tmp_path / "cwd"
    home_dir.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.chdir(cwd)
    return home_dir


def _tilde_user(us: FileUserSource, name: str, root: str = "~/.blue-userdb-lib") -> None:
    """The library walkthrough in guide.md: every store path starts with ``~/``."""
    base = f"{root}/sources/{name}"
    asyncio.run(us.create_user(
        name,
        registry_props=_json_file(Path(f"{root}/registries/{name}.json")),
        kb_source_props={"_class": _KB_FILE, "connection": {"protocol": "kb/file", "directory": base}},
        metadata_source_props=_json_file(Path(f"{base}/metadata.json")),
        contact_source_props=_json_file(Path(f"{base}/contacts.json")),
        session_source_props=_json_file(Path(f"{base}/sessions.json")),
        onboard=False,
    ))


def test_tilde_paths_are_written_and_deleted_under_home(home: Path) -> None:
    us = FileUserSource("us", {"connection": {"path": "~/.blue-userdb-lib/registry.json"}, "console": False})
    _tilde_user(us, "alice")
    us.set_metadata("alice", "identity.name", "Alice")

    user_dir = home / ".blue-userdb-lib" / "sources" / "alice"
    assert (user_dir / "metadata.json").exists()
    assert not Path("~").exists()  # nothing written to a literal ./~
    assert "~" not in str(us.get_user("alice"))  # the expanded path is recorded

    assert asyncio.run(us.delete_user("alice")) == []
    assert not list(user_dir.glob("*.json"))
    assert not (home / ".blue-userdb-lib" / "registries" / "alice.json").exists()


def test_the_library_walkthrough_leaves_the_clis_user_alone(home: Path) -> None:
    """The quickstart: the CLI's alice under ~/.blue-userdb, then the library's.

    Deleting the library's alice used to remove the CLI's (#171).
    """
    registry = home / ".blue-userdb" / "registry.json"
    cli = FileUserSource("user_source", {"connection": {"path": str(registry)}, "console": False})
    cli.create_database("alice")
    cli.set_metadata("alice", "identity.name", "Alice (CLI)")

    us = FileUserSource("us", {"connection": {"path": "~/.blue-userdb-lib/registry.json"}, "console": False})
    _tilde_user(us, "alice")
    assert asyncio.run(us.delete_user("alice")) == []

    fresh = FileUserSource("user_source", {"connection": {"path": str(registry)}, "console": False})
    assert fresh.get_metadata("alice", "identity.name") == "Alice (CLI)"


def test_a_legacy_tilde_record_never_reaches_home(
    home: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A path recorded literally before #171 names the ./~ its store wrote, not $HOME."""
    victim = home / "metadata.json"
    victim.write_text("{}")
    us = _source(data_dir)
    # Created as an older version did: "~" recorded and written unexpanded.
    monkeypatch.setattr("blue_data_user_source.source._expand_user_paths", lambda props: props)
    us.create_database("gina", {"metadata_source": _json_file(Path("~/metadata.json"))})
    assert Path("~/metadata.json").exists()  # the literal ./~ the store wrote

    refused = asyncio.run(us.delete_user("gina"))

    assert victim.exists()
    assert refused == ["~/metadata.json"]  # outside the data directory, so kept


def test_a_base_user_source_expands_its_registry_path(home: Path) -> None:
    """lib/README.md's construction: UserSource with a "~/..." registry file."""
    us = UserSource("user_source", {"registry": _json_file(Path("~/.blue-userdb-lib/registry.json"))})
    us.create_database("hal")
    assert (home / ".blue-userdb-lib" / "registry.json").exists()
    assert not Path("~").exists()
