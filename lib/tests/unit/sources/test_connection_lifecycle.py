"""Tests for UserSource's connection-properties init and connect API (#64).

Registry construction used to happen imperatively inside ``UserSource.__init__``,
bypassing the ``DataSource`` connect lifecycle entirely. It's now wired through
``_initialize_connection_properties``/``_connect``/``_disconnect`` like every
other ``DataSource`` subclass in ``blue-data`` (``FileJSONSource``,
``NEO4JSource``, etc.).
"""
from __future__ import annotations

from pathlib import Path

from blue_data.registry.data_registry import DataRegistry

from blue_data_user_source.file_user_source import FileUserSource
from blue_data_user_source.memory_user_source import MemoryUserSource
from blue_data_user_source.source import UserSource


def test_default_connection_protocol_names_the_family_only() -> None:
    """A bare UserSource has no registry backend of its own to name, so the
    second segment is absent rather than filled with a non-backend label."""
    source = UserSource("us")
    assert source.properties["connection"]["protocol"] == "user"


def test_memory_user_source_overrides_protocol() -> None:
    source = MemoryUserSource()
    assert source.properties["connection"]["protocol"] == "user/memory"


def test_file_user_source_overrides_protocol_and_sets_path(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    source = FileUserSource("us", {"connection": {"path": str(registry_path)}})
    assert source.properties["connection"]["protocol"] == "user/file"
    assert source.properties["connection"]["path"] == str(registry_path)


def test_init_connects_and_populates_registry_and_connection() -> None:
    source = MemoryUserSource("us")
    assert isinstance(source._registry, DataRegistry)
    assert source.connection is source._registry


def test_init_starts_with_empty_manager_cache() -> None:
    source = MemoryUserSource("us")
    assert source._managers == {}


def test_source_record_is_registered_via_connected_registry() -> None:
    """Regression guard: __init__ no longer builds the registry itself —
    it relies on _connect() having run first (via DataSource.__init__)."""
    source = MemoryUserSource("us")
    record = source._registry.get_source_record("us")
    assert record is not None
    assert record["properties"]["_class"].endswith("MemoryUserSource")


def test_disconnect_clears_registry_and_managers() -> None:
    source = MemoryUserSource("us")
    source._disconnect()
    assert source._registry is None
    assert source._managers == {}


def test_reconnect_rebuilds_registry_and_resets_manager_cache() -> None:
    source = MemoryUserSource("us")
    source._managers["stale"] = object()  # simulate a cached manager from before reconnect

    new_registry = source._connect(**source.properties["connection"])

    assert isinstance(new_registry, DataRegistry)
    assert source._registry is new_registry
    assert source._managers == {}


def test_file_user_source_connect_creates_working_registry(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    source = FileUserSource("us", {"connection": {"path": str(registry_path)}})
    assert registry_path.exists()
    assert isinstance(source._registry, DataRegistry)
    assert source._registry.get_source_record("us") is not None
