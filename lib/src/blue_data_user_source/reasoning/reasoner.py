from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from blue_data_user_source.reasoning.metric import (
    CompletenessMetric,
    FreshnessMetric,
    MetricEvaluation,
    PrivacyMetric,
    UserDataMetric,
)

if TYPE_CHECKING:
    from blue_data_user_source.data.manager import UserDataManager
    from blue_data_user_source.source import UserSource
    from blue_data_user_source.types import QueryResult


def _summarize_schema_facets(schema: dict) -> str:
    """Render a KB schema export as a compact list of queryable facets.

    Used to ground sub-question generation in what the data store can actually
    answer: per-entity attributes (e.g. PERSON's AGE, NATIONALITY) and
    relations between entities (e.g. PERSON --HAS_SKILL--> SKILL), excluding
    structural IS_SUBCLASS_OF edges.
    """
    lines: list[str] = []
    for name, entity in schema.get("entities", {}).items():
        attrs = list((entity.get("contents") or {}).get("attributes") or {})
        if attrs:
            lines.append(f"{name} attributes: {', '.join(attrs)}")
    for rel in schema.get("relations", {}).values():
        if rel.get("name") == "IS_SUBCLASS_OF":
            continue
        desc = f" ({rel['description']})" if rel.get("description") else ""
        lines.append(f"{rel.get('source')} --{rel.get('name')}--> {rel.get('target')}{desc}")
    return "\n".join(lines)


def _strip_json_fences(text: str) -> str:
    """Remove markdown ```json … ``` fences that models sometimes add."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[: text.rfind("```")]
    return text.strip()


async def _llm_complete(
    prompt: str,
    model: str = "gpt-4o",
    properties: dict | None = None,
) -> str | dict:
    """Call the LLM and return a string or parsed dict.

    Pass ``properties={"response_format": "json_object"}`` to request a JSON
    object response.  The OpenAI ``response_format`` parameter is set
    accordingly and the returned value is a parsed ``dict`` rather than a
    string.  For plain-text calls the return value is ``str``.
    """
    props = properties or {}
    want_json = props.get("response_format") == "json_object"
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI()
        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if want_json:
            kwargs["response_format"] = {"type": "json_object"}
        resp = await client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        if want_json:
            try:
                return json.loads(_strip_json_fences(content))
            except (json.JSONDecodeError, ValueError):
                return {}
        return content
    except Exception:
        return {} if want_json else ""


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
        query_id: str | None = None,
    ) -> None:
        self._source = source
        self._manager = manager
        self._session_id = session_id
        self._query_id = query_id
        self._metrics: list[UserDataMetric] = list(self._DEFAULT_METRICS)
        if manager is not None:
            self._metrics.append(PrivacyMetric(manager=manager))

    async def contextualize_query(self, query: str) -> str:
        user_name = "the user"
        if self._manager is not None:
            user_name = self._manager.get_metadata("identity.name") or self._manager._database

        prompt = (
            "Rewrite the following query about a user's personal data so that it is a "
            "clear, well-formed question, and so that every reference to the user is "
            f"replaced by the user's name, \"{user_name}\".\n\n"
            "Replace references such as \"you\", \"your\", \"the user\", \"he\", \"she\", "
            "\"his\", \"her\", the user's own name, or any other identity reference that "
            f"points to the user — with \"{user_name}\" (or the possessive "
            f"\"{user_name}'s\" where appropriate). Only rewrite references to the user "
            "themself; leave references to other people unchanged.\n\n"
            "Example (user's name is \"Alice\"): \"what is your age\", \"What is the "
            "user's age\", \"what is her age\", and \"you age?\" all become "
            "\"what is Alice's age\".\n\n"
            "Return only the rewritten query, with no explanation.\n\n"
            f"Query: {query}"
        )
        result = await _llm_complete(prompt)
        return result or query

    async def expand_query(self, query: str) -> list[str]:
        user_name = "the user"
        schema_summary = ""
        if self._manager is not None:
            user_name = self._manager.get_metadata("identity.name") or self._manager._database
            try:
                schema = await self._manager._ensure_kb_source().export_database_schema(
                    self._manager._database
                )
                schema_summary = _summarize_schema_facets(schema)
            except Exception:
                schema_summary = ""

        schema_block = (
            f"Facets the data store can actually answer about {user_name}:\n{schema_summary}\n\n"
            if schema_summary else ""
        )

        prompt = (
            f"The following is a query about {user_name}'s personal data, to be answered by "
            f"searching a personal data store:\n\"{query}\"\n\n"
            f"{schema_block}"
            "Decompose the query into standalone supplemental sub-questions that, together, "
            "would help answer it. Requirements for each sub-question:\n"
            f"- It is a well-formed, third-person factual lookup about {user_name} (e.g. "
            f"\"What is {user_name}'s ...\"), phrased for searching the data store directly — "
            "never a question addressed to the user for clarification (no \"do you\", "
            "\"would you\", \"are you interested in\", and never ask the user to choose between "
            "options).\n"
            "- If facets are listed above, only use ones relevant to the query; ignore the "
            "irrelevant ones.\n"
            "- It targets a distinct facet — do not repeat or merely rephrase the original "
            "query or another sub-question.\n\n"
            "Scale the number of sub-questions to the query's complexity: a query that is "
            "already a single, specific, directly-answerable lookup needs none at all — return "
            "an empty list rather than inventing filler. A broad query spanning many facets may "
            "need up to 5. Never pad the list just to reach a quota.\n\n"
            'Return a JSON object: {"questions": ["<question>", ...]} (the list may be empty).'
        )
        result = await _llm_complete(prompt, properties={"response_format": "json_object"})
        questions = result.get("questions", []) if isinstance(result, dict) else []
        return questions[:5] if isinstance(questions, list) else []

    async def assess_query_results(
        self,
        query: str,
        query_results: list[Any],
        query_results_metadata: dict[str, Any],
    ) -> list[MetricEvaluation]:
        applicable = self._identify_user_data_metrics(query, query_results, query_results_metadata)
        return list(await asyncio.gather(*[
            metric.evaluate(query, query_results, query_results_metadata)
            for metric in applicable
        ]))

    async def assess_user_interaction(
        self,
        query: str,
        query_results: list[Any],
        query_results_metadata: dict[str, Any],
        user_data_metric_evaluation: list[MetricEvaluation],
    ) -> bool:
        for m in user_data_metric_evaluation:
            print(f"Metric {m.name}: score={m.score}, passes={m.passes}, reasoning={m.reasoning}")
        return any(not m.passes for m in user_data_metric_evaluation)

    async def request_user_interaction(
        self,
        query: str,
        data: list[Any],
        metadata: dict[str, Any],
        metrics: list[MetricEvaluation],
        topic: str | None = None,
    ) -> tuple[list[Any], dict[str, Any]]:
        from blue_data_user_source.interaction import ContactManager, SessionManager
        from blue_data_user_source.types import InteractionError, QueryError

        if self._manager is None:
            raise QueryError("No data manager available for user clarification")

        session_manager = SessionManager(
            database=self._manager._database, data_manager=self._manager
        )
        # Callers that go through UserSource._run_query always supply session_id/query_id
        # (reuse-or-create is decided there); direct callers get an ad hoc single-query
        # session here so every interaction still lands in a durable record.
        session_id = self._session_id or await session_manager.create_session()
        query_id = self._query_id or await session_manager.create_query(session_id, query)

        contact_manager = ContactManager(
            database=self._manager._database, data_manager=self._manager
        )
        channel = await contact_manager.identify_contact_method(topic=topic)

        failing_names = [m.name for m in metrics if not m.passes]
        raw_question = (
            f'To answer "{query}", I need more information. '
            f"The following data quality checks did not pass: {', '.join(failing_names)}. "
            "Could you provide additional details?"
        )

        user_name = self._manager.get_metadata("identity.name") or self._manager._database
        pronouns = self._manager.get_metadata("identity.pronouns")
        communication_style = self._manager.get_metadata("preferences.communication_style") or "neutral"
        verbosity = self._manager.get_metadata("preferences.verbosity") or "normal"
        language = self._manager.get_metadata("preferences.language") or "English"

        context_lines = [f"User's name: {user_name}"]
        if pronouns:
            context_lines.append(f"User's pronouns: {pronouns}")
        context_lines += [
            f"Contact method: {channel.protocol} ({channel.name})",
            f"Communication style: {communication_style}",
            f"Verbosity: {verbosity}",
            f"Language: {language}",
        ]

        prompt = (
            "Rewrite the following question to a user in a more natural way, "
            "addressing them directly (without mentioning their name). "
            "The user's name is provided so you can distinguish questions about them "
            "from questions about other people — do not turn questions about others into 'you' questions. "
            "If pronouns are provided, use them correctly for any third-person references. "
            "Return only the rewritten question.\n\n"
            f"Question: {raw_question}\n\n" + "\n".join(context_lines)
        )
        user_question = await _llm_complete(prompt)
        if not user_question:
            user_question = raw_question

        interaction_id = await session_manager.create_interaction(
            session_id, query_id, user_question, channel.protocol, channel.name
        )
        interaction = channel.interact(interaction_id=interaction_id)

        await interaction.start()
        try:
            response = await interaction.send(user_question)
        except InteractionError:
            await session_manager.mark_interaction_timeout(session_id, query_id, interaction_id)
            raise
        await interaction.stop()

        await session_manager.resolve_interaction(session_id, query_id, interaction_id, response)

        context = f"Question: {query}\nUser Response: {response}"
        await self._manager.store_data(context, queries=[query])

        return list(data) + [response], metadata

    async def resolve_via_interaction(
        self,
        query: str,
        assessment_query: str,
        data: list[Any],
        metadata: dict[str, Any],
        max_rounds: int = 3,
        topic: str | None = None,
    ) -> list[Any]:
        """Assess result quality and, if needed, resolve it via user interaction.

        Owns the full assess-then-interact cycle: evaluates quality metrics on
        ``data``/``metadata``, and while they don't all pass, asks the user for
        clarification and re-assesses the augmented result — up to ``max_rounds``
        times, stopping as soon as every metric passes.

        ``query`` is the original, user-facing query (used to phrase the question);
        ``assessment_query`` is the rewritten query used for metric evaluation.
        ``topic`` optionally scopes contact-method selection to a project/topic
        availability override (see ``ContactManager.identify_contact_method``).

        Returns only the newly collected user responses, in round order (empty if
        no interaction was needed).
        """
        new_items: list[Any] = []
        metrics = await self.assess_query_results(assessment_query, data, metadata)
        for _ in range(max_rounds):
            if not await self.assess_user_interaction(assessment_query, data, metadata, metrics):
                break
            data, metadata = await self.request_user_interaction(
                query, data, metadata, metrics, topic=topic
            )
            new_items.append(data[-1])
            metrics = await self.assess_query_results(assessment_query, data, metadata)
        return new_items

    def _locale_instruction(self) -> str:
        locale = self._manager.get_metadata("identity.locale") if self._manager is not None else None
        return (
            f" Format any dates, numbers, and currency amounts per {locale} locale conventions."
            if locale else ""
        )

    async def synthesize_results_nl(self, original_query: str, results: list[QueryResult]) -> str:
        pairs = "\n".join(f"Q: {r.query}\nA: {r.results}" for r in results)
        prompt = (
            f"The user asked: \"{original_query}\"\n\n"
            f"The following sub-questions were answered:\n{pairs}\n\n"
            "Write a clear, concise natural language response that directly answers the user's "
            f"original question using only the information above.{self._locale_instruction()} "
            "Do not mention sub-questions."
        )
        return await _llm_complete(prompt)

    async def synthesize_expanded_nl(self, results: list[QueryResult]) -> str:
        """Summarize the per-sub-question queries and raw results as prose.

        Used for the "expanded"/supplemental section when ``output_form`` is
        "nl" — a few flowing paragraphs organized by topic, not a Q/A
        transcript and not raw JSON.
        """
        pairs = "\n".join(
            f"Q: {r.query}\nA: {json.dumps(r.results, default=str)}" for r in results
        )
        prompt = (
            "While answering a user's question, the following sub-questions were "
            f"explored, along with their raw results:\n{pairs}\n\n"
            "Write a few short paragraphs of natural language, organized by topic, "
            f"summarizing this supplemental information for the user.{self._locale_instruction()} "
            "Do not use a Q: / A: transcript format, and do not include raw JSON or data "
            "structures — write flowing prose."
        )
        return await _llm_complete(prompt)

    async def synthesize_results_json(
        self, original_query: str, results: list[QueryResult]
    ) -> list[dict[str, Any]]:
        """Aggregate results from all expanded sub-questions into a single JSON table.

        Unlike ``synthesize_results_nl``, which produces prose, this returns a
        flat JSON array of rows sharing a schema derived from the original
        query — e.g. for "what are alice's skills and their proficiency?" each
        row would be ``{"skill": ..., "proficiency": ...}``.
        """
        pairs = "\n".join(
            f"Q: {r.query}\nA: {json.dumps(r.results, default=str)}" for r in results
        )
        prompt = (
            f"The user asked: \"{original_query}\"\n\n"
            f"The following sub-questions were answered:\n{pairs}\n\n"
            "Aggregate the information above into a single table that directly answers the "
            "user's original question. Every row must use the same set of keys, chosen to fit "
            "the original question. Do not include sub-questions, duplicates, or rows unrelated "
            "to the original question.\n"
            'Return only a JSON object of the form: {"rows": [{...}, ...]}'
        )
        result = await _llm_complete(prompt, properties={"response_format": "json_object"})
        rows = result.get("rows", []) if isinstance(result, dict) else []
        return rows if isinstance(rows, list) else []

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
