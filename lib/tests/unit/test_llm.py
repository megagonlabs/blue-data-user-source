"""LLM calls go to the BLUE_DATA_LLM_PROVIDER provider, through LiteLLM (#190).

Every call went to OpenAI, so a deployment set up for Anthropic could not run
user-source on Claude. `litellm.acompletion` is stubbed: these tests check what
would be sent, and where.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from blue_data_user_source import LLMError, llm
from blue_data_user_source.reasoning.reasoner import UserQueryReasoner, _llm_complete

_MODEL_VARS = ("BLUE_DATA_LLM_MODEL", "BLUE_DATA_USER_SOURCE_LLM_MODEL",
               "BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL",
               "BLUE_DATA_USER_SOURCE_EXTRACTION_LLM_MODEL")


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BLUE_DATA_LLM_PROVIDER", *_MODEL_VARS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")


def _reply(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def acompletion():
    stub = AsyncMock(return_value=_reply("ok"))
    with patch("litellm.acompletion", stub):
        yield stub


@pytest.mark.parametrize("setting, expected", [
    (None, "openai"), ("", "openai"), ("OpenAI", "openai"), (" anthropic ", "anthropic"),
])
def test_the_provider_is_the_deployments_blank_meaning_openai(
    monkeypatch, setting, expected,
) -> None:
    if setting is not None:
        monkeypatch.setenv("BLUE_DATA_LLM_PROVIDER", setting)
    assert llm.provider() == expected


@pytest.mark.parametrize("provider, model", [
    ("openai", "gpt-4o"), ("anthropic", "claude-opus-4-8"),
])
async def test_a_call_goes_to_the_provider_with_its_default_model(
    monkeypatch, acompletion, provider, model,
) -> None:
    monkeypatch.setenv("BLUE_DATA_LLM_PROVIDER", provider)
    assert await _llm_complete("q") == "ok"
    kwargs = acompletion.await_args.kwargs
    # Pinned, so LiteLLM dispatches on the setting, not on the model's name.
    assert (kwargs["custom_llm_provider"], kwargs["model"]) == (provider, model)


async def test_the_family_model_is_used_under_any_provider(monkeypatch, acompletion) -> None:
    """#175 sent BLUE_DATA_LLM_MODEL only under openai; it now belongs to the provider."""
    monkeypatch.setenv("BLUE_DATA_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("BLUE_DATA_LLM_MODEL", "claude-sonnet-4-8")
    await _llm_complete("q")
    assert acompletion.await_args.kwargs["model"] == "claude-sonnet-4-8"


def test_model_resolution_order(monkeypatch) -> None:
    assert llm.configured_model("REASONING") == "gpt-4o"
    monkeypatch.setenv("BLUE_DATA_LLM_MODEL", "family")
    assert llm.configured_model("REASONING") == "family"
    monkeypatch.setenv("BLUE_DATA_USER_SOURCE_LLM_MODEL", "package")
    assert llm.configured_model("REASONING") == "package"
    monkeypatch.setenv("BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL", "reasoning")
    assert llm.configured_model("REASONING") == "reasoning"
    assert llm.configured_model("EXTRACTION") == "package"


def test_the_reasoner_resolves_its_model_when_given_none(monkeypatch) -> None:
    monkeypatch.setenv("BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL", "gpt-4o-mini")
    assert UserQueryReasoner(source=None)._model == "gpt-4o-mini"  # type: ignore[arg-type]
    assert UserQueryReasoner(source=None, model="o3")._model == "o3"  # type: ignore[arg-type]


async def test_the_providers_own_key_is_required(monkeypatch, acompletion) -> None:
    monkeypatch.setenv("BLUE_DATA_LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("OPENAI_API_KEY")  # not needed by anthropic, not asked for
    with pytest.raises(llm.MissingKeyError, match="ANTHROPIC_API_KEY is not set") as info:
        await _llm_complete("q")
    assert isinstance(info.value, LLMError) and info.value.env == "ANTHROPIC_API_KEY"
    acompletion.assert_not_awaited()


async def test_an_unknown_provider_needs_a_model_named(monkeypatch, acompletion) -> None:
    monkeypatch.setenv("BLUE_DATA_LLM_PROVIDER", "mistral")
    with pytest.raises(LLMError, match="no default model for BLUE_DATA_LLM_PROVIDER='mistral'"):
        await _llm_complete("q")
    monkeypatch.setenv("BLUE_DATA_LLM_MODEL", "mistral-large-latest")
    await _llm_complete("q")  # no key check for a provider user-source doesn't know
    assert acompletion.await_args.kwargs["custom_llm_provider"] == "mistral"


@pytest.mark.parametrize("content", [
    '{"score": 1}',
    '```json\n{"score": 1}\n```',
    'Here is the assessment:\n{"score": 1}',  # no JSON mode outside OpenAI
    '{"score": 1}\nI scored it high because...',
])
async def test_a_json_reply_is_read_with_or_without_a_json_mode(acompletion, content) -> None:
    acompletion.return_value = _reply(content)
    assert await _llm_complete("q", properties={"response_format": "json_object"}) == {"score": 1}
    assert acompletion.await_args.kwargs["response_format"] == {"type": "json_object"}
