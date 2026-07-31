from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from blue_data_user_source.reasoning.metric import (
    CompletenessMetric,
    FreshnessMetric,
    MetricEvaluation,
    UserDataMetric,
)

if TYPE_CHECKING:
    from blue_data_user_source.data.manager import UserDataManager
    from blue_data_user_source.source import UserSource
    from blue_data_user_source.types import QueryResult


async def _llm_complete(prompt: str, model: str = "gpt-4o") -> str:
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI()
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""
    except Exception:
        return ""


class UserQueryReasoner:
    """Orchestrates query rewriting, assessment, and interaction for a user database."""

    _DEFAULT_METRICS: list[UserDataMetric] = [
        CompletenessMetric(),
        FreshnessMetric(),
    ]

    def __init__(
        self,
        source: UserSource,
        manager: UserDataManager | None = None,
        session_id: str | None = None,
    ) -> None:
        self._source = source
        self._manager = manager
        self._session_id = session_id
        self._metrics: list[UserDataMetric] = list(self._DEFAULT_METRICS)

    async def contextualize_query(self, query: str) -> str:
        prompt = (
            "Rewrite the following user query to be more precise for searching "
            f"a personal user data store. Return only the rewritten query.\n\nQuery: {query}"
        )
        result = await _llm_complete(prompt)
        return result or query

    async def expand_query(self, query: str) -> list[str]:
        prompt = (
            f"Given this query about a user's personal data: \"{query}\"\n"
            "List 3-5 specific supplemental questions that would help answer the original query. "
            "If the original query is already specific, return it as the only item. "
            "Return a JSON array of question strings only."
        )
        response = await _llm_complete(prompt)
        try:
            questions: list[str] = json.loads(response.strip())
        except (json.JSONDecodeError, ValueError):
            questions = [query]
        return questions

    async def assess_query_results(
        self,
        query: str,
        query_results: list[Any],
        query_results_metadata: dict[str, Any],
    ) -> list[MetricEvaluation]:
        applicable = self._identify_user_data_metrics(query, query_results, query_results_metadata)
        return [
            await metric.evaluate(query, query_results, query_results_metadata)
            for metric in applicable
        ]

    async def assess_user_verification(
        self,
        query: str,
        query_results: list[Any],
        query_results_metadata: dict[str, Any],
        user_data_metric_evaluation: list[MetricEvaluation],
    ) -> bool:
        return any(not m.passes for m in user_data_metric_evaluation)

    async def request_user_clarification(
        self,
        query: str,
        data: list[Any],
        metadata: dict[str, Any],
        metrics: list[MetricEvaluation],
    ) -> tuple[list[Any], dict[str, Any]]:
        from blue_data_user_source.interaction import ContactManager
        from blue_data_user_source.types import QueryError

        if self._manager is None:
            raise QueryError("No data manager available for user clarification")

        contact_manager = ContactManager(
            database=self._manager._database, data_manager=self._manager
        )
        channel = await contact_manager.identify_contact_method(query)
        interaction = channel.interact()

        failing_names = [m.name for m in metrics if not m.passes]
        clarification_question = (
            f"To answer \"{query}\", I need more information. "
            f"The following data quality checks did not pass: {', '.join(failing_names)}. "
            "Could you provide additional details?"
        )

        await interaction.start()
        response = await interaction.send(clarification_question)
        await interaction.stop()

        context = f"Question: {query}\nUser Response: {response}"
        await self._manager.store_data(context, queries=[query])

        return list(data) + [response], metadata

    async def synthesize_results_nl(self, original_query: str, results: list[QueryResult]) -> str:
        pairs = "\n".join(f"Q: {r.query}\nA: {r.results}" for r in results)
        prompt = (
            f"The user asked: \"{original_query}\"\n\n"
            f"The following sub-questions were answered:\n{pairs}\n\n"
            "Write a clear, concise natural language response that directly answers the user's "
            "original question using only the information above. Do not mention sub-questions."
        )
        return await _llm_complete(prompt)

    async def synthesize_data_nl(self, entries: list[dict]) -> str:
        lines = []
        for e in entries:
            value = e.get("value", "")
            lines.append(f"- {e.get('key', e.get('name', ''))}: {value}")
        prompt = (
            f"The following attributes are stored about a user:\n{chr(10).join(lines)}\n\n"
            "Write a concise natural language summary of this information."
        )
        return await _llm_complete(prompt)

    async def synthesize_metadata_nl(self, entries: list[dict]) -> str:
        lines = []
        for e in entries:
            lines.append(
                f"- source at {e.get('location', e.get('id', 'unknown'))}, "
                f"registered {e.get('registered_at', 'unknown')}"
            )
        prompt = (
            f"The following sources are registered in a user database:\n{chr(10).join(lines)}\n\n"
            "Write a concise natural language summary of these sources."
        )
        return await _llm_complete(prompt)

    def _identify_user_data_metrics(
        self,
        query: str,
        query_results: list[Any],
        query_results_metadata: dict[str, Any],
    ) -> list[UserDataMetric]:
        return [
            m for m in self._metrics
            if m._is_applicable(query, query_results, query_results_metadata)
        ]
