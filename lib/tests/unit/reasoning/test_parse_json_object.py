"""The JSON object in a reply from a provider with no JSON mode (#190, #204)."""
from __future__ import annotations

import pytest

from blue_data_user_source.reasoning.reasoner import _parse_json_object


@pytest.mark.parametrize("reply", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    'Here you go:\n```json\n{"a": 1}\n```',
    'Using {name} as a key:\n```json\n{"a": 1}\n```',
    'Using {name} and {} as keys: {"a": 1}',
    '{"a": 1} is what {you} asked for.',
])
def test_the_object_is_found(reply: str) -> None:
    assert _parse_json_object(reply) == {"a": 1}


def test_a_reply_with_only_an_empty_object_is_that_object() -> None:
    assert _parse_json_object("Nothing to report: {}") == {}


@pytest.mark.parametrize("reply", ["", "no object here", "only {words} in braces"])
def test_a_reply_with_no_object_raises(reply: str) -> None:
    with pytest.raises(ValueError):
        _parse_json_object(reply)
