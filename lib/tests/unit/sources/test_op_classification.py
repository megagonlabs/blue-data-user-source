"""Every op UserSource serves is classified for blue-data's read-only guard (#188).

blue-data's guard is deny-by-default (blue-data's registry write-op guard fix): a dict or
JSON op runs without ``optional_properties["commit"]`` only when the source lists
it in ``_READ_OPS``; one in ``_WRITE_OPS``, or in neither, needs ``commit``. Each
op a source serves belongs to exactly one set. UserSource serves none: its
``execute_query`` answers every query as natural language.
"""
from __future__ import annotations

import inspect
import json
import re

import pytest

from blue_data_user_source import FileUserSource, MemoryUserSource, RedisUserSource, UserSource

_SOURCES = [UserSource, FileUserSource, MemoryUserSource, RedisUserSource]

# The ops UserSource serves: none (see the module docstring).
_SERVED_OPS: frozenset[str] = frozenset()

# Reading a query's "op" is how a source dispatches dict or JSON ops.
_OP_DISPATCH = re.compile(r"""\[\s*["']op["']\s*\]|\.get\(\s*["']op["']""")


def _runs_read_only(source: type[UserSource], query: object) -> bool:
    """blue-data's deny-by-default decision for *query* without ``commit``."""
    if isinstance(query, str):
        try:
            query = json.loads(query)
        except ValueError:
            return True  # not an op: a plain query string has no op guard here
    op = query.get("op") if isinstance(query, dict) else None
    return isinstance(op, str) and op.upper() in source._READ_OPS


@pytest.mark.parametrize("cls", _SOURCES)
def test_both_sets_are_frozensets_of_upper_case_names(cls: type[UserSource]) -> None:
    for ops in (cls._READ_OPS, cls._WRITE_OPS):
        assert isinstance(ops, frozenset)
        assert all(isinstance(op, str) and op == op.upper() for op in ops)


def test_user_source_declares_both_sets() -> None:
    assert "_READ_OPS" in vars(UserSource)
    assert "_WRITE_OPS" in vars(UserSource)


@pytest.mark.parametrize("cls", _SOURCES)
def test_every_served_op_is_in_exactly_one_set(cls: type[UserSource]) -> None:
    assert not cls._READ_OPS & cls._WRITE_OPS
    assert cls._READ_OPS | cls._WRITE_OPS == _SERVED_OPS


@pytest.mark.parametrize("cls", _SOURCES)
def test_no_op_dispatch_left_unclassified(cls: type[UserSource]) -> None:
    """A source that starts reading a query's "op" must add its ops to _SERVED_OPS and a set."""
    assert not _OP_DISPATCH.search(inspect.getsource(cls))


@pytest.mark.parametrize("cls", _SOURCES)
def test_natural_language_runs_and_an_op_needs_commit(cls: type[UserSource]) -> None:
    assert _runs_read_only(cls, "What is my name?")
    assert not _runs_read_only(cls, {"op": "SET_METADATA", "key": "identity.name"})
    assert not _runs_read_only(cls, json.dumps({"op": "DELETE_USER"}))
