"""UserSource.import_data must match DataSource.import_data's signature — a
positional call valid against the base class should bind the same arguments
here. It previously had `database` and `collection` swapped (with `collection`
missing its default), so a base-typed caller would silently bind the wrong
argument (#25 follow-up).
"""
from __future__ import annotations

import inspect

from blue_data.source.source import DataSource

from blue_data_user_source.source import UserSource


def test_import_data_signature_matches_base_class() -> None:
    base_params = list(inspect.signature(DataSource.import_data).parameters.values())
    override_params = list(inspect.signature(UserSource.import_data).parameters.values())

    def _shape(p: inspect.Parameter) -> tuple:
        return (p.name, p.default, p.kind)

    assert [_shape(p) for p in override_params] == [_shape(p) for p in base_params]


def test_import_data_positional_call_binds_database_not_collection() -> None:
    source = UserSource("us")
    calls: list[tuple] = []

    class _FakeManager:
        async def import_data(self, src, collection, entity, mode, options):
            calls.append((src, collection, entity, mode, options))
            return {}

    source._get_manager = lambda database: (calls.append(("database", database)) or _FakeManager())

    fake_source = object()
    source.import_data(fake_source, "alice")  # positional: source, database — matches base

    assert calls[0] == ("database", "alice")
    assert calls[1] == (fake_source, "default", None, "append", None)
