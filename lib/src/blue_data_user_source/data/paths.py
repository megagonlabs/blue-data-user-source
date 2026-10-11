"""Backend-agnostic reads of dot-notation paths in a JSONSource (#99).

``RedisJSONSource.get`` returns ``[]`` for a missing sub-path, where the file
and memory backends return ``None``, and it also returns ``[]`` for a stored
empty list, so the two cannot be told apart from its result. Code that tested
``get(path) is None`` therefore misread every missing record on Redis: schema
seeding skipped all but the first category, a missing contact came back as a
contact with ``[]`` details, and a missing metadata key read as ``[]``.

Reading the path's root document (``metadata``, ``contacts``, ``sessions``) —
which every backend returns as a dict, or ``None`` when absent — and walking
the rest in Python gives one answer on all of them.
"""
from __future__ import annotations

from typing import Any


def get_path(store: Any, path: str) -> Any:
    """The value at dot-separated *path* in *store*, or ``None`` when any part is absent."""
    root, _, rest = path.partition(".")
    node = store.get(root)
    if not rest:
        return None if node == [] else node
    for part in rest.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node
