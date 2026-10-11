"""After the user answers, reassessment sees the answer as fresh evidence (#125).

The reply used to be appended to the results while the provenance stayed the
same, so a clarification could fix completeness but never freshness: stale
data stayed stale through every round, and the user was asked again and again.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.reasoning.metric import FreshnessMetric, MetricEvaluation
from blue_data_user_source.reasoning.reasoner import UserQueryReasoner

_TWO_YEARS_AGO = (datetime.now(timezone.utc) - timedelta(days=730)).isoformat()
_STALE = {"n1": {"source": "kb", "extraction": "Alice lives in New York", "created": _TWO_YEARS_AGO,
                 "modified": _TWO_YEARS_AGO}}
_FAILING = [MetricEvaluation(name="freshness", score=0.1, reasoning="", passes=False)]


def _contact_manager(*replies: str) -> MagicMock:
    interaction = AsyncMock()
    interaction.send = AsyncMock(side_effect=list(replies))
    method = MagicMock(protocol="email", name="work")
    method.interact.return_value = interaction
    cm = MagicMock()
    cm.identify_contact_method = AsyncMock(return_value=method)
    return cm


def _reasoner(manager: UserDataManager) -> UserQueryReasoner:
    return UserQueryReasoner(source=MagicMock(console=True), manager=manager)


async def _ask(reasoner: UserQueryReasoner, *replies: str):
    with patch("blue_data_user_source.interaction.ContactManager", return_value=_contact_manager(*replies)), \
         patch.object(reasoner._manager, "store_data", AsyncMock()), \
         patch("blue_data_user_source.reasoning.reasoner._llm_complete",
               AsyncMock(return_value="Do you still live in New York?")):
        return await reasoner.request_user_interaction("where do I live?", ["New York"], _STALE, _FAILING)


async def test_the_reply_gets_fresh_provenance_of_its_own(manager: UserDataManager) -> None:
    data, metadata = await _ask(_reasoner(manager), "Yes, still in New York.")

    assert data == ["New York", "Yes, still in New York."]
    assert metadata["n1"] == _STALE["n1"]  # the old evidence is kept as it was
    [reply_key] = [k for k in metadata if k.startswith("user-reply:")]
    reply = metadata[reply_key]
    assert reply["source"] == "user via email"
    assert "Yes, still in New York." in reply["extraction"]
    assert "Do you still live in New York?" in reply["extraction"]
    age = datetime.now(timezone.utc) - datetime.fromisoformat(reply["modified"])
    assert age < timedelta(minutes=1)


async def test_the_input_metadata_is_not_mutated(manager: UserDataManager) -> None:
    before = {k: dict(v) for k, v in _STALE.items()}
    await _ask(_reasoner(manager), "Yes.")
    assert _STALE == before


async def test_a_blank_reply_adds_no_evidence(manager: UserDataManager) -> None:
    _, metadata = await _ask(_reasoner(manager), "   ")
    assert metadata == _STALE


async def test_a_confirmation_can_repair_freshness(manager: UserDataManager) -> None:
    """End to end through the real FreshnessMetric: stale data fails, the user
    confirms, and the reassessment sees a reply that is 0 days old."""
    reasoner = _reasoner(manager)
    reasoner._metrics = [FreshnessMetric()]
    prompts: list[str] = []

    async def llm(prompt, model="gpt-4o", properties=None):
        if properties and properties.get("response_format") == "json_object":
            prompts.append(prompt)
            fresh = ": 0 day(s) old" in prompt  # not the tail of "730 day(s) old"
            return {"score": 0.9 if fresh else 0.1, "reasoning": "fresh" if fresh else "stale"}
        return "Do you still live in New York?"

    with patch("blue_data_user_source.interaction.ContactManager",
               return_value=_contact_manager("Yes, still in New York.", "unused")), \
         patch.object(reasoner._manager, "store_data", AsyncMock()), \
         patch("blue_data_user_source.reasoning.reasoner._llm_complete", llm):
        new_items = await reasoner.resolve_via_interaction(
            "where do I live?", "where does Alice live?", ["New York"], _STALE, max_rounds=3
        )

    assert new_items == ["Yes, still in New York."]  # asked once, not three times
    assert len(prompts) == 2
    assert ": 0 day(s) old" not in prompts[0]
    assert ": 730 day(s) old" in prompts[1] and ": 0 day(s) old" in prompts[1]


async def test_freshness_sees_what_each_node_is_and_where_it_came_from() -> None:
    """Ages alone made a fresh confirmation indistinguishable from unrelated new data;
    live, gpt-4o kept failing freshness "without information about their content"."""
    prompts: list[str] = []

    async def llm(prompt, model="gpt-4o", properties=None):
        prompts.append(prompt)
        return {"score": 1.0, "reasoning": ""}

    metadata = {**_STALE, "user-reply:i1": {"source": "user via email",
                "extraction": "The user answered 'Still in NY?': yes",
                "created": datetime.now(timezone.utc).isoformat()}}
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", llm):
        await FreshnessMetric().evaluate("where?", [], metadata)

    [prompt] = prompts
    assert "- n1: 730 day(s) old (source: kb) — Alice lives in New York" in prompt
    assert "- user-reply:i1: 0 day(s) old (source: user via email) — The user answered" in prompt
    assert "answer the user has just given" in prompt


async def test_a_blank_reply_is_not_stored(manager: UserDataManager) -> None:
    """An empty answer (e.g. EOF on a console) used to run a KB extraction over nothing."""
    reasoner = _reasoner(manager)
    store = AsyncMock()
    with patch("blue_data_user_source.interaction.ContactManager", return_value=_contact_manager("  ")), \
         patch.object(reasoner._manager, "store_data", store), \
         patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(return_value="Where?")):
        await reasoner.request_user_interaction("where do I live?", [], {}, _FAILING)
    store.assert_not_awaited()
