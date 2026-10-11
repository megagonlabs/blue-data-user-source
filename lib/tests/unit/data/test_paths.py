"""Dot-path reads give one answer on every JSONSource backend (#99).

`RedisJSONSource.get` returns [] for a missing sub-path, where file and memory
return None; code testing `get(path) is None` misread every missing record on
Redis. `_RedisLikeStore` reproduces that contract without a Redis server.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from blue_data_user_source.data.paths import get_path

_SRC = Path(__file__).parents[3] / "src" / "blue_data_user_source" / "data"


class _RedisLikeStore:
    """A dict-backed store with RedisJSONSource's get(): [] for a missing sub-path."""

    def __init__(self) -> None:
        self.docs: dict[str, Any] = {}

    def get(self, path: str | None = None) -> Any:
        root, _, rest = (path or "").partition(".")
        node = self.docs.get(root)
        if not rest:
            return node
        for part in rest.split("."):
            if not isinstance(node, dict) or part not in node:
                return []
            node = node[part]
        return node

    def set(self, path: str, value: Any) -> None:
        root, _, rest = path.partition(".")
        if not rest:
            self.docs[root] = value
            return
        node = self.docs.setdefault(root, {})
        *parents, last = rest.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[last] = value


def test_get_path_is_none_for_missing_parts_and_keeps_stored_values() -> None:
    store = _RedisLikeStore()
    store.set("metadata", {"identity": {"name": "Ana", "pronouns": None}, "privacy": {"sensitive_categories": []}})
    assert store.get("metadata.identity.timezone") == []          # the ambiguity being fixed
    assert get_path(store, "metadata.identity.timezone") is None
    assert get_path(store, "metadata.nope.x") is None
    assert get_path(store, "contacts") is None
    assert get_path(store, "metadata.identity.name") == "Ana"
    assert get_path(store, "metadata.privacy.sensitive_categories") == []   # a stored empty list survives


async def test_seeding_on_a_redis_like_store_seeds_every_category_and_protocol(monkeypatch) -> None:
    from blue_data_user_source.data.manager import UserDataManager

    meta, contacts = _RedisLikeStore(), _RedisLikeStore()
    mgr = UserDataManager("ana", {"backend": "memory"})
    monkeypatch.setattr(mgr, "_ensure_metadata_source", lambda: meta)
    monkeypatch.setattr(mgr, "_ensure_contact_source", lambda: contacts)

    mgr.seed_metadata_schema(str(_SRC / "metadata_schema.json"))
    mgr.seed_contact_schema(str(_SRC / "contact_schema.json"))

    metadata_schema = json.loads((_SRC / "metadata_schema.json").read_text())
    contact_schema = json.loads((_SRC / "contact_schema.json").read_text())
    assert set(meta.docs["metadata"]) == set(metadata_schema)          # was: only "identity"
    assert set(contacts.docs["contacts"]) == set(contact_schema)       # was: only "email"
    assert mgr.get_metadata("identity.timezone") is None               # was: []
    assert mgr.get_contact("email", "work") is None                    # was: []
