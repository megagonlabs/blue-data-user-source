"""Keep account identifiers out of committed VCR cassettes (#131).

Request ``authorization`` headers are filtered by each runner's VCR config.
Responses carry more: the OpenAI organization and project ids, and Cloudflare
cookies. None of it is needed to replay a cassette, so it is dropped when a
response is recorded (``before_record_response``), and ``python -m
tests.benchmarks.common.cassettes`` scrubs cassettes already on disk.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

SCRUBBED_RESPONSE_HEADERS = frozenset({"openai-organization", "openai-project", "set-cookie"})


def scrub_response(response: dict[str, Any]) -> dict[str, Any]:
    headers = response.get("headers") or {}
    for name in list(headers):
        if name.lower() in SCRUBBED_RESPONSE_HEADERS:
            del headers[name]
    return response


def scrub_file(path: Path) -> int:
    """Scrub one cassette in place; returns how many headers were removed."""
    data = yaml.safe_load(path.read_text())
    removed = 0
    for interaction in (data or {}).get("interactions", []):
        headers = interaction.get("response", {}).get("headers") or {}
        before = len(headers)
        scrub_response(interaction["response"])
        removed += before - len(headers)
    if removed:
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return removed


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent
    total = sum(scrub_file(p) for p in sorted(root.glob("*/cassettes/*.yaml")))
    print(f"Removed {total} header(s) from cassettes under {root}")
