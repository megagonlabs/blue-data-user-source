"""LLM calls, sent through LiteLLM to the deployment's provider (#190).

The reasoner, the quality metrics and the contact selection call `AsyncClient`,
which has the OpenAI client's shape (`client.chat.completions.create(...)`);
LiteLLM answers in OpenAI's response shape whatever the provider. The KB's
agents (answering, extraction) go through blue-data-kb-source's own client,
which follows the same provider setting.

Which provider answers is the deployment's: BLUE_DATA_LLM_PROVIDER, blank meaning
`openai`, as in blue-data-ops and blue-data-kb-source. Every call carries it as
`custom_llm_provider`, so LiteLLM dispatches on the deployment's setting instead
of inferring a route from the model string. The family model, BLUE_DATA_LLM_MODEL,
names a model of that provider; unset, each provider has its default (blue-data's
base spec: claude-opus-4-8 / gpt-4o).
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

from blue_data_user_source.types import LLMError

# LiteLLM writes records below WARNING to stdout, which under an MCP server is the
# JSON-RPC stream (#199). It reads this once, on import, and the KB's client can be
# the first to import it, so it is set here rather than before our own call.
os.environ.setdefault("LITELLM_LOG", "WARNING")

PROVIDER_ENV = "BLUE_DATA_LLM_PROVIDER"
DEFAULT_PROVIDER = "openai"
DEFAULT_MODELS = {"openai": "gpt-4o", "anthropic": "claude-opus-4-8"}
# The variable each provider's key is read from. A provider not listed here is
# still served; LiteLLM reports its own missing key at call time.
API_KEY_ENVS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}

# The packages whose exceptions mean "the model could not be reached or refused
# the call" rather than a bug of ours: LiteLLM's, and the SDKs and HTTP client
# it raises through.
_UPSTREAM_PACKAGES = frozenset({"litellm", "openai", "anthropic", "httpx", "httpcore", "aiohttp"})


class MissingKeyError(LLMError):
    """The provider's API key variable is not set; `env` names it."""

    def __init__(self, env: str) -> None:
        super().__init__(f"{env} is not set; {PROVIDER_ENV}={provider()!r} needs it for LLM calls")
        self.env = env


def provider() -> str:
    """The provider this deployment's LLM calls go to."""
    return os.environ.get(PROVIDER_ENV, "").strip().lower() or DEFAULT_PROVIDER


def default_model() -> str:
    """The provider's default model, for a call that names none."""
    name = provider()
    if name not in DEFAULT_MODELS:
        raise LLMError(
            f"no default model for {PROVIDER_ENV}={name!r}: set BLUE_DATA_LLM_MODEL "
            "(or a BLUE_DATA_USER_SOURCE_*_LLM_MODEL) to one of its models"
        )
    return DEFAULT_MODELS[name]


def configured_model(function: str | None = None) -> str:
    """The model configured for *function* (REASONING or EXTRACTION): the function's
    variable, then the package-wide one, then the family-wide one, then the
    provider's default. The CLI resolves the same chain from a profile."""
    names = [f"BLUE_DATA_USER_SOURCE_{function}_LLM_MODEL"] if function else []
    names += ["BLUE_DATA_USER_SOURCE_LLM_MODEL", "BLUE_DATA_LLM_MODEL"]
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    return default_model()


def api_key_env() -> str | None:
    """The variable the provider's key is read from, when user-source knows it."""
    return API_KEY_ENVS.get(provider())


def missing_key() -> str | None:
    """The key variable the provider needs and the environment lacks, if any."""
    env = api_key_env()
    return env if env and not os.environ.get(env) else None


def is_upstream_error(exc: BaseException) -> bool:
    """Whether *exc* came from LiteLLM, a provider SDK or the HTTP client under them."""
    return any(c.__module__.split(".")[0] in _UPSTREAM_PACKAGES for c in type(exc).__mro__)


class AsyncClient:
    """An OpenAI-shaped async client whose completions LiteLLM sends to `provider()`.

    `model=None` means the provider's default."""

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, *, model: str | None = None, **kwargs: Any) -> Any:
        # LiteLLM otherwise downloads its model price map on import; user-source
        # uses none of it, and the bundled copy keeps an import off the network.
        os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
        try:
            import litellm
        except ImportError as exc:
            raise LLMError(
                "LLM calls require LiteLLM: pip install 'litellm>=1.102,<1.106'"
            ) from exc
        env = missing_key()
        if env:
            raise MissingKeyError(env)
        # LiteLLM otherwise prints its help banner on every failed call.
        litellm.suppress_debug_info = True
        # Its aiohttp transport leaves SSL connections bound to the caller's event
        # loop; once `asyncio.run` closes that loop they are torn down at exit with
        # an "Event loop is closed" traceback. httpx's transport is not.
        litellm.disable_aiohttp_transport = True
        return await litellm.acompletion(
            model=model or default_model(), custom_llm_provider=provider(), **kwargs
        )
