"""An LLM failure is an error, never an empty result (#117).

`_llm_complete` used to return {} or "" for every failure, and each caller
turned that into a believable "nothing found": an outage looked like a user
with no data. The calls go through LiteLLM (#190), so the errors are
LiteLLM's; `litellm.acompletion` is the stubbed call point.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import litellm
import pytest

from blue_data_user_source import LLMError, MemoryUserSource
from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.interaction.contact import ContactManager
from blue_data_user_source.reasoning.reasoner import _llm_complete

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


@pytest.fixture(autouse=True)
def _openai(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default provider and model, with a key set so calls reach the stub."""
    for name in ("BLUE_DATA_LLM_PROVIDER", "BLUE_DATA_LLM_MODEL", "BLUE_DATA_USER_SOURCE_LLM_MODEL",
                 "BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def _completion(stub: AsyncMock):
    return patch("litellm.acompletion", stub)


def _reply(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.mark.parametrize("error", [
    litellm.APIConnectionError("refused", llm_provider="openai", model="gpt-4o", request=_REQUEST),
    litellm.Timeout("too slow", model="gpt-4o", llm_provider="openai"),
    litellm.AuthenticationError("bad key", llm_provider="openai", model="gpt-4o"),
    litellm.RateLimitError("slow down", llm_provider="openai", model="gpt-4o"),
    litellm.NotFoundError("no such model", model="gpt-4o", llm_provider="openai"),
])
@pytest.mark.parametrize("json_mode", [False, True])
async def test_provider_errors_raise_llm_error(error, json_mode) -> None:
    props = {"response_format": "json_object"} if json_mode else None
    with _completion(AsyncMock(side_effect=error)):
        with pytest.raises(LLMError, match=r"LLM call to 'gpt-4o' \(openai\) failed") as info:
            await _llm_complete("q", properties=props)
    assert info.value.__cause__ is error


async def test_missing_credentials_raise_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    stub = AsyncMock()
    with _completion(stub), pytest.raises(LLMError, match="OPENAI_API_KEY is not set"):
        await _llm_complete("q")
    stub.assert_not_awaited()  # checked before the call, not reported by the provider


@pytest.mark.parametrize("content", ["not json", "[1, 2]", ""])
async def test_unusable_json_replies_raise_llm_error(content) -> None:
    with _completion(AsyncMock(return_value=_reply(content))):
        with pytest.raises(LLMError, match="JSON"):
            await _llm_complete("q", properties={"response_format": "json_object"})


async def test_good_replies_come_back_unchanged() -> None:
    with _completion(AsyncMock(return_value=_reply('```json\n{"a": 1}\n```'))):
        assert await _llm_complete("q", properties={"response_format": "json_object"}) == {"a": 1}
    with _completion(AsyncMock(return_value=_reply("hello"))):
        assert await _llm_complete("q") == "hello"
    with _completion(AsyncMock(return_value=_reply(None))):
        assert await _llm_complete("q") == ""  # an empty text reply is a reply, not a failure


async def test_bugs_in_our_own_code_are_not_disguised() -> None:
    with _completion(AsyncMock(side_effect=TypeError("bad kwarg"))):
        with pytest.raises(TypeError, match="bad kwarg"):
            await _llm_complete("q")


async def test_a_query_fails_loudly_when_the_llm_is_down() -> None:
    us = MemoryUserSource("llm-down", {"console": False})
    await us.create_user(
        "alice", registry_props={"backend": "memory"}, kb_source_props={"backend": "memory"},
        metadata_source_props={"backend": "memory"}, contact_source_props={"backend": "memory"},
        session_source_props={"backend": "memory"}, onboard=False,
    )
    down = AsyncMock(side_effect=litellm.APIConnectionError(
        "refused", llm_provider="openai", model="gpt-4o",
    ))
    with _completion(down):
        with pytest.raises(LLMError, match="failed"):  # was: ([], session_id), as if alice had no data
            await us._run_query("what are my skills?", database="alice")


async def test_channel_choice_keeps_its_documented_fallback(manager: UserDataManager, user_id: str) -> None:
    """The one caller that still falls back: picking among several contact methods."""
    cm = ContactManager(user_id, manager)
    await cm.create_contact_method("email", "work", {"address": "a@example.com"}, preference=2)
    await cm.create_contact_method("webhook", "bot", {"url": "http://example.com"}, preference=1)
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(side_effect=LLMError("down"))):
        channel = await cm.identify_contact_method()
    assert (channel.protocol, channel.name) == ("webhook", "bot")  # lowest preference
