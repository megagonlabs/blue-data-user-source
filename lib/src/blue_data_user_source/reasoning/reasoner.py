from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from llama_index.core import Settings  # type: ignore[import-untyped]

from blue_data_user_source.reasoning.metric import (
    CompletenessMetric,
    FreshnessMetric,
    MetricEvaluation,
    UserDataMetric,
)

if TYPE_CHECKING:
    from blue_data_user_source.source import UserSource
    from blue_data_user_source.types import QueryResult


class UserQueryReasoner:
    """Orchestrates query rewriting, assessment, and interaction for a user database."""

    _DEFAULT_METRICS: list[UserDataMetric] = [
        CompletenessMetric(),
        FreshnessMetric(),
    ]

    def __init__(
        self,
        source: UserSource,
        database: str,
        session_id: str | None = None,
    ) -> None:
        self._source = source
        self._database = database
        self._session_id = session_id
        self._metrics: list[UserDataMetric] = list(self._DEFAULT_METRICS)

    async def contextualize_query(self, query: str) -> str:
        """Rewrite the query to be suitable for user data retrieval."""
        llm = Settings.llm
        prompt = f"Rewrite the following user query to be more precise for searching " f"a personal user data store. Return only the rewritten query.\n\nQuery: {query}"
        response = await llm.acomplete(prompt)
        print(response)
        return str(response).strip()

    async def expand_query(self, query: str) -> list[str]:
        """Return complementary questions that provide context for the original query."""
        llm = Settings.llm
        prompt = (
            f"Given this query about a user's personal data: \"{query}\"\n"
            "List 3-5 specific supplemental questions that would could be used to answer the original query"
            "If original query is already specific, return it as the only item in the list."
            "Return a JSON array of question strings only."
        )
        response = await llm.acomplete(prompt)
        try:
            questions: list[str] = json.loads(str(response).strip())
        except (json.JSONDecodeError, ValueError):
            questions = [query]
        print(questions)
        return questions

    async def assess_query_results(
        self,
        query: str,
        query_results: list[Any],
        query_results_metadata: dict[str, Any],
    ) -> list[MetricEvaluation]:
        """Return metric evaluations for applicable quality dimensions."""
        applicable = self._identify_user_data_metrics(query, query_results, query_results_metadata)
        return [await metric.evaluate(query, query_results, query_results_metadata) for metric in applicable]

    async def assess_user_verification(
        self,
        query: str,
        query_results: list[Any],
        query_results_metadata: dict[str, Any],
        user_data_metric_evaluation: list[MetricEvaluation],
    ) -> bool:
        """Return True if user interaction is needed to improve result quality."""
        return any(not m.passes for m in user_data_metric_evaluation)

    async def request_user_clarification(
        self,
        query: str,
        data: list[Any],
        metadata: dict[str, Any],
        metrics: list[MetricEvaluation],
    ) -> tuple[list[Any], dict[str, Any]]:
        """Invoke the Interaction Layer and return updated data after clarification."""
        from blue_data_user_source.interaction import ContactManager

        contact_manager = ContactManager(database=self._database, data_manager=self._source._data_manager)
        channel = await contact_manager.identify_contact_method(query)
        interaction = channel.interact()

        failing_names = [m.name for m in metrics if not m.passes]
        # Verification: stale data needs refresh; Clarification: missing data needs new input
        is_verification = any(m.name == "freshness" for m in metrics if not m.passes)

        clarification_question = (
            f"To answer \"{query}\", I need more information. " f"The following data quality checks did not pass: {', '.join(failing_names)}. " "Could you provide additional details?"
        )

        await interaction.start()
        response = await interaction.send(clarification_question)
        await interaction.stop()

        # Combine question and response as the context to extract new data
        context = f"Question: {query}\n User Response: {response}"

        source_query = query if is_verification else clarification_question
        schema = await self._source._data_manager._llm_extract_schema(self._database, source_query)
        extracted, sources = await self._source._data_manager._llm_extract_data(self._database, source_query, schema, [context])
        for key, values in extracted.items():
            await self._source._data_manager.store_data(self._database, key, values, source_text=sources.get(key))

        return list(data) + [response], metadata

    async def synthesize_results_nl(self, original_query: str, results: list[QueryResult]) -> str:
        """Synthesize a list of sub-question results into a single natural language answer."""
        llm = Settings.llm
        pairs = "\n".join(f"Q: {r.query}\nA: {r.results}" for r in results)
        prompt = (
            f"The user asked: \"{original_query}\"\n\n"
            f"The following sub-questions were answered:\n{pairs}\n\n"
            "Write a clear, concise natural language response that directly answers the user's original question "
            "using only the information above. Do not mention sub-questions."
        )
        return str(await llm.acomplete(prompt)).strip()

    async def synthesize_data_nl(self, entries: list[dict]) -> str:
        """Describe a list of data entries in natural language using the LLM."""
        llm = Settings.llm
        lines = []
        for e in entries:
            values = ", ".join(str(v) for v in e.get("value", []))
            meta = e.get("metadata") or {}
            date_part = f" (as of {meta['date']})" if meta.get("date") else ""
            lines.append(f"- {e.get('key', '')}: {values}{date_part}")
        formatted = "\n".join(lines)
        prompt = f"The following attributes are stored about a user:\n{formatted}\n\n" "Write a concise natural language summary of this information."
        return str(await llm.acomplete(prompt)).strip()

    async def synthesize_metadata_nl(self, entries: list[dict]) -> str:
        """Describe a list of source metadata entries in natural language using the LLM."""
        llm = Settings.llm
        lines = []
        for e in entries:
            queries_part = f", with queries: {', '.join(str(q) for q in e['queries'])}" if e.get("queries") else ""
            lines.append(f"- {e.get('source_type', 'unknown')} source at {e.get('location', 'unknown')}, " f"registered {e.get('registered_at', 'unknown')}{queries_part}")
        formatted = "\n".join(lines)
        prompt = f"The following sources are registered in a user database:\n{formatted}\n\n" "Write a concise natural language summary of these sources."
        return str(await llm.acomplete(prompt)).strip()

    def _identify_user_data_metrics(
        self,
        query: str,
        query_results: list[Any],
        query_results_metadata: dict[str, Any],
    ) -> list[UserDataMetric]:
        return [m for m in self._metrics if m._is_applicable(query, query_results, query_results_metadata)]
