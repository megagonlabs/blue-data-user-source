from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from blue_data_user_source.data.manager import UserDataManager


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

    def _threshold(self) -> float:
        """Score cutoff for ``passes`` (score >= threshold).

        Defaults to the class-level ``THRESHOLD``. Subclasses that want their
        pass bar to move with user metadata (e.g. stricter privacy scrutiny
        for a lower consent level) override this — see ``PrivacyMetric``.
        """
        return self.THRESHOLD


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
            passes=score >= self._threshold(),
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

        from blue_data_user_source.reasoning.reasoner import _llm_complete

        now = datetime.now(timezone.utc)
        node_age_lines: list[str] = []
        for node_id, m in query_results_metadata.items():
            if not isinstance(m, dict):
                continue
            ts_str = m.get("modified") or m.get("created")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_days = (now - ts).days
                node_age_lines.append(f"- {node_id}: {age_days} day(s) old")
            except ValueError:
                pass

        if not node_age_lines:
            return MetricEvaluation(
                name="freshness", score=0.0, reasoning="No provenance timestamps available.", passes=False
            )

        nodes_section = "\n".join(node_age_lines)
        prompt = (
            f"Query: {query}\n"
            f"Data node ages:\n{nodes_section}\n"
            "On a scale of 0.0 to 1.0, how fresh is this data for answering the query? "
            "Consider that data older than one year is typically stale. "
            'Reply with a JSON object: {"score": <float>, "reasoning": <string>}'
        )
        parsed = await _llm_complete(prompt, properties={"response_format": "json_object"})
        score: float = float(parsed.get("score", 0.0)) if isinstance(parsed, dict) else 0.0
        reasoning: str = str(parsed.get("reasoning", "")) if isinstance(parsed, dict) else ""
        return MetricEvaluation(
            name="freshness",
            score=score,
            reasoning=reasoning,
            passes=score >= self._threshold(),
        )


class PrivacyMetric(UserDataMetric):
    """Measures whether query results comply with the user's privacy preferences."""

    # privacy.consent_level -> pass threshold. Lower consent means less tolerance
    # for privacy risk, so the score must be higher to pass.
    _CONSENT_LEVEL_THRESHOLDS: dict[str, float] = {
        "minimal": 0.8,
        "standard": 0.6,
        "full": 0.4,
    }

    def __init__(
        self,
        manager: "UserDataManager | None" = None,
        properties: dict[str, object] | None = None,
    ) -> None:
        super().__init__(properties)
        self._manager = manager

    def _threshold(self) -> float:
        if self._manager is not None:
            consent_level = self._manager.get_metadata("privacy.consent_level")
            if consent_level in self._CONSENT_LEVEL_THRESHOLDS:
                return self._CONSENT_LEVEL_THRESHOLDS[consent_level]
        return self.THRESHOLD

    async def evaluate(
        self,
        query: str,
        query_results: list[Any],
        query_results_metadata: dict[str, Any],
    ) -> MetricEvaluation:
        from blue_data_user_source.reasoning.reasoner import _llm_complete

        privacy_lines: list[str] = []
        if self._manager is not None:
            for key in ("data_sharing_preference", "sensitive_categories", "retention_days", "consent_level"):
                value = self._manager.get_metadata(f"privacy.{key}")
                if value is not None:
                    privacy_lines.append(f"- {key}: {value}")

        privacy_section = (
            f"User privacy preferences:\n{chr(10).join(privacy_lines)}\n"
            if privacy_lines
            else "User privacy preferences: not specified.\n"
        )

        prompt = (
            f"Query: {query}\n"
            f"Results: {query_results}\n"
            f"{privacy_section}"
            "On a scale of 0.0 to 1.0, how well do these results respect the user's privacy preferences? "
            "A score of 1.0 means no privacy concerns; 0.0 means a serious privacy violation. "
            'Reply with a JSON object: {"score": <float>, "reasoning": <string>}'
        )
        parsed = await _llm_complete(prompt, properties={"response_format": "json_object"})
        score: float = float(parsed.get("score", 0.0)) if isinstance(parsed, dict) else 0.0
        reasoning: str = str(parsed.get("reasoning", "")) if isinstance(parsed, dict) else ""
        return MetricEvaluation(
            name="privacy",
            score=score,
            reasoning=reasoning,
            passes=score >= self._threshold(),
        )
