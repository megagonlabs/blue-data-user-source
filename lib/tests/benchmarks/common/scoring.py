"""Scoring functions for user-source benchmarks.

``judge_alignment`` is an LLM-backed semantic match between expected and actual
text fragments (used for extraction and querying).  ``judge_rewrite_quality``
and ``judge_expansion_quality`` score reasoning outputs.
``judge_appropriateness`` evaluates whether a generated question suits its
contact protocol.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# ── LLM tool definitions ──────────────────────────────────────────────────────

_CONTAINS_TOOL = {
    "type": "function",
    "function": {
        "name": "record_contains_result",
        "description": "Record whether an answer contains an expected piece of information.",
        "parameters": {
            "type": "object",
            "properties": {
                "found": {
                    "type": "boolean",
                    "description": "True if the answer contains the expected information (even if phrased differently).",
                },
                "reasoning": {
                    "type": "string",
                    "description": "One-sentence justification.",
                },
            },
            "required": ["found", "reasoning"],
        },
    },
}

_REWRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "record_rewrite_quality",
        "description": "Score whether a rewritten query is more precise and semantically related to the original.",
        "parameters": {
            "type": "object",
            "properties": {
                "score": {
                    "type": "number",
                    "description": "0.0–1.0: 1.0 = significantly more precise and stays on-topic; 0.0 = off-topic or worse.",
                },
                "reasoning": {"type": "string"},
            },
            "required": ["score", "reasoning"],
        },
    },
}

_EXPANSION_TOOL = {
    "type": "function",
    "function": {
        "name": "record_expansion_quality",
        "description": "Score whether sub-questions are relevant to the original query and helpful for answering it.",
        "parameters": {
            "type": "object",
            "properties": {
                "relevance_score": {
                    "type": "number",
                    "description": "0.0–1.0: fraction of sub-questions semantically related to the original.",
                },
                "coverage_score": {
                    "type": "number",
                    "description": "0.0–1.0: how well the set of sub-questions covers the original query's information need.",
                },
                "reasoning": {"type": "string"},
            },
            "required": ["relevance_score", "coverage_score", "reasoning"],
        },
    },
}

_APPROPRIATENESS_TOOL = {
    "type": "function",
    "function": {
        "name": "record_appropriateness",
        "description": "Judge whether a generated interaction question is appropriate for its delivery channel.",
        "parameters": {
            "type": "object",
            "properties": {
                "score": {
                    "type": "number",
                    "description": (
                        "0.0–1.0. Consider: tone matches channel formality, length is suitable "
                        "(concise and conversational for stdio, a terminal prompt; richer for email; "
                        "self-contained and chat-length for webhook, which another app shows the user), "
                        "language is natural."
                    ),
                },
                "reasoning": {"type": "string"},
            },
            "required": ["score", "reasoning"],
        },
    },
}


# ── Score dataclasses ─────────────────────────────────────────────────────────

@dataclass
class ContainsResult:
    expected: str
    found: bool
    reasoning: str


@dataclass
class ExtractionCaseScore:
    case_id: str
    model: str
    per_query: list[dict[str, Any]] = field(default_factory=list)  # {question, expected, results}
    hit_rate: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_seconds: float = 0.0


@dataclass
class QueryCaseScore:
    case_id: str
    model: str
    addressing_style: str
    hit_rate: float = 0.0
    per_expected: list[ContainsResult] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_seconds: float = 0.0


@dataclass
class ReasoningCaseScore:
    case_id: str
    model: str
    benchmark_type: str
    score: float = 0.0
    secondary_score: float | None = None
    reasoning: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_seconds: float = 0.0
    # Metric cases: the metric's pass/fail decision, what the case expects, and
    # whether they agree. A metric's raw score is not "higher is better" (an
    # empty result set *should* score 0 on completeness), so the decision is
    # what a regression check compares.
    passes: bool | None = None
    expect_pass: bool | None = None
    correct: bool | None = None


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _results_to_text(results: list[Any]) -> str:
    parts: list[str] = []
    for r in results:
        if isinstance(r, dict):
            parts.append(json.dumps(r))
        else:
            parts.append(str(r))
    return "\n".join(parts) if parts else "(no results)"


_JUDGE_ATTEMPTS = 3


async def _judge_contains(answer_text: str, expected: str, client: Any, model: str) -> ContainsResult:
    # A judge reply is occasionally malformed (truncated tool-call JSON). Retry;
    # if it never parses, record "not found" with the reason instead of
    # aborting every remaining case of the run.
    for _ in range(_JUDGE_ATTEMPTS):
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You judge whether an answer contains a specific piece of information (semantic, not literal)."},
                {"role": "user", "content": f"Answer:\n{answer_text}\n\nDoes it contain: {expected!r}?"},
            ],
            tools=[_CONTAINS_TOOL],
            tool_choice={"type": "function", "function": {"name": "record_contains_result"}},
        )
        try:
            args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
            break
        except (json.JSONDecodeError, TypeError, IndexError):
            continue
    else:
        return ContainsResult(expected=expected, found=False,
                              reasoning=f"judge reply unparseable after {_JUDGE_ATTEMPTS} attempts")
    return ContainsResult(
        expected=expected,
        found=bool(args.get("found")),
        reasoning=str(args.get("reasoning", "")),
    )


async def score_extraction_case(
    case: Any,
    run_result: Any,
    judge_client: Any,
    judge_model: str,
) -> ExtractionCaseScore:
    from .cases import ExtractionCase
    score = ExtractionCaseScore(
        case_id=case.id,
        model=run_result.model,
        prompt_tokens=run_result.prompt_tokens,
        completion_tokens=run_result.completion_tokens,
        latency_seconds=run_result.latency_seconds,
    )
    hits = 0
    total = 0
    for qa in case.queries:
        answer_text = _results_to_text(run_result.answers.get(qa.question, []))
        per_q: dict[str, Any] = {"question": qa.question, "answer": answer_text, "checks": []}
        for expected in qa.expected_contains:
            result = await _judge_contains(answer_text, expected, judge_client, judge_model)
            per_q["checks"].append({"expected": expected, "found": result.found, "reasoning": result.reasoning})
            if result.found:
                hits += 1
            total += 1
        score.per_query.append(per_q)
    score.hit_rate = hits / total if total else 0.0
    return score


async def score_query_case(
    case: Any,
    run_result: Any,
    judge_client: Any,
    judge_model: str,
) -> QueryCaseScore:
    score = QueryCaseScore(
        case_id=case.id,
        model=run_result.model,
        addressing_style=case.addressing_style,
        prompt_tokens=run_result.prompt_tokens,
        completion_tokens=run_result.completion_tokens,
        latency_seconds=run_result.latency_seconds,
    )
    answer_text = _results_to_text(run_result.results)
    hits = 0
    for expected in case.expected_contains:
        result = await _judge_contains(answer_text, expected, judge_client, judge_model)
        score.per_expected.append(result)
        if result.found:
            hits += 1
    score.hit_rate = hits / len(case.expected_contains) if case.expected_contains else 1.0
    return score


async def score_reasoning_case(
    case: Any,
    run_result: Any,
    judge_client: Any,
    judge_model: str,
) -> ReasoningCaseScore:
    score = ReasoningCaseScore(
        case_id=case.id,
        model=run_result.model,
        benchmark_type=case.benchmark_type,
        prompt_tokens=run_result.prompt_tokens,
        completion_tokens=run_result.completion_tokens,
        latency_seconds=run_result.latency_seconds,
    )

    if case.benchmark_type == "contextualization":
        rewritten = str(run_result.output)
        resp = await judge_client.chat.completions.create(
            model=judge_model,
            messages=[
                {"role": "system", "content": "You evaluate whether a query rewrite improves precision for searching a personal user data store."},
                {"role": "user", "content": f"Original: {case.query!r}\nRewrite: {rewritten!r}"},
            ],
            tools=[_REWRITE_TOOL],
            tool_choice={"type": "function", "function": {"name": "record_rewrite_quality"}},
        )
        args = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)
        score.score = float(args.get("score", 0.0))
        score.reasoning = str(args.get("reasoning", ""))

    elif case.benchmark_type == "expansion":
        questions = run_result.output if isinstance(run_result.output, list) else []
        resp = await judge_client.chat.completions.create(
            model=judge_model,
            messages=[
                {"role": "system", "content": "You evaluate whether sub-questions are relevant and cover a user data query."},
                {"role": "user", "content": f"Original: {case.query!r}\nSub-questions:\n" + "\n".join(f"- {q}" for q in questions)},
            ],
            tools=[_EXPANSION_TOOL],
            tool_choice={"type": "function", "function": {"name": "record_expansion_quality"}},
        )
        args = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)
        score.score = float(args.get("relevance_score", 0.0))
        score.secondary_score = float(args.get("coverage_score", 0.0))
        score.reasoning = str(args.get("reasoning", ""))

    elif case.benchmark_type in ("freshness", "completeness", "privacy"):
        from blue_data_user_source.reasoning.metric import MetricEvaluation
        ev: MetricEvaluation = run_result.output
        score.score = ev.score
        score.reasoning = ev.reasoning
        score.passes = ev.passes
        score.expect_pass = case.expect_pass
        if case.expect_pass is not None:
            score.correct = ev.passes == case.expect_pass

    elif case.benchmark_type == "appropriateness":
        question_text = str(run_result.output)
        resp = await judge_client.chat.completions.create(
            model=judge_model,
            messages=[
                {"role": "system", "content": "You evaluate whether an AI-generated question is appropriate for its delivery channel."},
                {"role": "user", "content": f"Channel: {case.contact_protocol!r}\nGenerated question:\n{question_text}"},
            ],
            tools=[_APPROPRIATENESS_TOOL],
            tool_choice={"type": "function", "function": {"name": "record_appropriateness"}},
        )
        args = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)
        score.score = float(args.get("score", 0.0))
        score.reasoning = str(args.get("reasoning", ""))

    return score
