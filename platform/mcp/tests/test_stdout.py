"""Stdout is the JSON-RPC stream of the MCP stdio transport (#199).

FastMCP sets the root logger to INFO, and LiteLLM writes records below WARNING to
stdout, so each LLM call put non-protocol lines in the stream. Run in a process of
its own: LiteLLM reads its log level once, on import.
"""
from __future__ import annotations

import os
import subprocess
import sys

_SCRIPT = """
import logging
import blue_data_user_mcp.server
import litellm
assert logging.getLogger().getEffectiveLevel() == logging.INFO
log = logging.getLogger("LiteLLM")
log.info("LiteLLM completion() model= gpt-4o; provider = openai")
log.warning("a warning")
"""


def _run(**env: str) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if k != "LITELLM_LOG"}
    return subprocess.run(
        [sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=120,
        env={**clean, "LITELLM_LOCAL_MODEL_COST_MAP": "True", **env},
    )


def test_litellm_writes_nothing_to_stdout() -> None:
    done = _run()
    assert done.returncode == 0, done.stderr
    assert done.stdout == ""
    assert "a warning" in done.stderr


def test_an_explicit_litellm_log_is_kept() -> None:
    done = _run(LITELLM_LOG="INFO")
    assert done.returncode == 0, done.stderr
    assert "provider = openai" in done.stdout
