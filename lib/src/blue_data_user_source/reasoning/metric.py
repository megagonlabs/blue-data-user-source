import json
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
        """Return completeness score based on result volume."""
        from blue_data_user_source.reasoning.reasoner import _llm_complete
        prompt = (
            f"Query: {query}\n"
            f"Results: {query_results}\n"
            "On a scale of 0.0 to 1.0, how complete is this result set for answering "
            'the query? Reply with a JSON object: {"score": <float>, "reasoning": <string>}'
        )
        response = await _llm_complete(prompt)
        try:
            parsed = json.loads(response)
        except (json.JSONDecodeError, ValueError):
            parsed = {}
        score: float = float(parsed.get("score", 0.0))
        reasoning: str = str(parsed.get("reasoning", ""))
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
        """Return freshness score based on provenance timestamps."""
        from datetime import datetime, timezone

        provenance: list[dict[str, Any]] = query_results_metadata.get("provenance", [])
        if not provenance:
            return MetricEvaluation(
                name="freshness", score=0.0, reasoning="No provenance available.", passes=False
            )

        now = datetime.now(timezone.utc)
        scores: list[float] = []
        for entry in provenance:
            ts_str = entry.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str)
                age_days = (now - ts).days
                # Linear decay: score = 1.0 at 0 days, 0.0 at 365 days
                scores.append(max(0.0, 1.0 - age_days / 365.0))
            except ValueError:
                scores.append(0.0)

        score = sum(scores) / len(scores)
        return MetricEvaluation(
            name="freshness",
            score=score,
            reasoning=f"Average age-based freshness over {len(scores)} sources.",
            passes=score >= self.THRESHOLD,
        )
