from dataclasses import dataclass
from typing import Any


@dataclass
class MetricEvaluation:
    """Score and reasoning for one quality dimension."""

    name: str
    score: float
    reasoning: str
    passes: bool


class UserDataMetric:
    """Evaluates one quality dimension of query results."""

    THRESHOLD: float = 0.6

    def __init__(self, properties: dict[str, object] | None = None) -> None:
        self._properties = properties or {}

    async def evaluate(
        self,
        query: str,
        query_results: list[Any],
        query_results_metadata: dict[str, Any],
    ) -> MetricEvaluation:
        """Return a metric evaluation report including score and reasoning."""
        raise NotImplementedError

    def _is_applicable(
        self,
        query: str,
        query_results: list[Any],
        query_results_metadata: dict[str, Any],
    ) -> bool:
        return True


class CompletenessMetric(UserDataMetric):
    """Measures whether enough information is available to answer the query."""

    async def evaluate(
        self,
        query: str,
        query_results: list[Any],
        query_results_metadata: dict[str, Any],
    ) -> MetricEvaluation:
        from blue_data_user_source.reasoning.reasoner import _llm_complete

        provenance_lines = [
            f"- {m['extraction']} (source: {m.get('source') or 'unknown'})"
            for m in query_results_metadata.values()
            if isinstance(m, dict) and m.get("extraction")
        ]
        provenance_section = (
            f"Provenance:\n{chr(10).join(provenance_lines)}\n" if provenance_lines else ""
        )
        prompt = (
            f"Query: {query}\n"
            f"Results: {query_results}\n"
            f"{provenance_section}"
            "On a scale of 0.0 to 1.0, how complete is this result set for answering "
            'the query? Reply with a JSON object: {"score": <float>, "reasoning": <string>}'
        )
        parsed = await _llm_complete(prompt, properties={"response_format": "json_object"})
        score: float = float(parsed.get("score", 0.0)) if isinstance(parsed, dict) else 0.0
        reasoning: str = str(parsed.get("reasoning", "")) if isinstance(parsed, dict) else ""
        return MetricEvaluation(
            name="completeness",
            score=score,
            reasoning=reasoning,
            passes=score >= self.THRESHOLD,
        )


class FreshnessMetric(UserDataMetric):
    """Measures whether the information is sufficiently recent."""

    async def evaluate(
        self,
        query: str,
        query_results: list[Any],
        query_results_metadata: dict[str, Any],
    ) -> MetricEvaluation:
        from datetime import datetime, timezone

        # metadata_acc values: {id, type, name, created, modified, extraction, source, ...}
        timestamps: list[str] = []
        for m in query_results_metadata.values():
            if not isinstance(m, dict):
                continue
            ts = m.get("modified") or m.get("created")
            if ts:
                timestamps.append(ts)

        if not timestamps:
            return MetricEvaluation(
                name="freshness", score=0.0, reasoning="No provenance timestamps available.", passes=False
            )

        now = datetime.now(timezone.utc)
        scores: list[float] = []
        for ts_str in timestamps:
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_days = (now - ts).days
                scores.append(max(0.0, 1.0 - age_days / 365.0))
            except ValueError:
                scores.append(0.0)

        score = sum(scores) / len(scores)
        return MetricEvaluation(
            name="freshness",
            score=score,
            reasoning=f"Average age-based freshness over {len(scores)} cited nodes.",
            passes=score >= self.THRESHOLD,
        )
