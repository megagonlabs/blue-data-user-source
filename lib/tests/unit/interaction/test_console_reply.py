"""Asking the user at this process's console (the ``stdio`` channel).

End of input is no answer (#174): under a pipe, a script or /dev/null, EOF was
recorded as an empty ``resolved`` reply, and the query asked again, up to three
times, with nobody there. And the asker is told when a question starts and ends
(#185), so a CLI can pause its live status display around it.
"""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.interaction.session import SessionManager
from blue_data_user_source.reasoning.metric import MetricEvaluation
from blue_data_user_source.reasoning.reasoner import UserQueryReasoner

_FAILING = [MetricEvaluation(name="completeness", score=0.0, reasoning="", passes=False)]


async def _ask(manager: UserDataManager, stdin: str, **callbacks) -> list:
    """A query whose checks always fail, asked at the console (no contact methods registered)."""
    reasoner = UserQueryReasoner(source=MagicMock(console=True), manager=manager)
    reasoner.assess_query_results = AsyncMock(return_value=_FAILING)  # type: ignore[method-assign]
    manager.store_data = AsyncMock()  # type: ignore[method-assign]  # no KB extraction of replies
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(return_value="Where do you live?")), \
         patch("sys.stdin", io.StringIO(stdin)), patch("sys.stdout", io.StringIO()):
        return await reasoner.resolve_via_interaction(
            "where do I live?", "where?", ["Berlin"], {}, max_rounds=3, **callbacks,
        )


async def _interactions(manager: UserDataManager, user_id: str) -> list[dict]:
    sessions = await SessionManager(database=user_id, data_manager=manager).list_sessions()
    return [ia for s in sessions.values() for q in s["queries"].values() for ia in q["interactions"].values()]


async def test_end_of_input_is_no_answer_and_ends_the_clarification(manager: UserDataManager, user_id: str) -> None:
    assert await _ask(manager, stdin="") == []

    [record] = await _interactions(manager, user_id)  # asked once, not three times
    assert record["status"] == "failed"
    assert "standard input is closed" in record["error"]
    assert not record.get("response")


async def test_a_typed_answer_is_still_resolved(manager: UserDataManager, user_id: str) -> None:
    """A reply, then end of input: the reply counts, and the next round ends cleanly."""
    assert await _ask(manager, stdin="Lisbon\n") == ["Lisbon"]

    records = await _interactions(manager, user_id)
    assert [r["status"] for r in records] == ["resolved", "failed"]
    assert records[0]["response"] == "Lisbon"


async def test_an_empty_line_is_a_blank_reply_not_end_of_input(manager: UserDataManager, user_id: str) -> None:
    assert await _ask(manager, stdin="\n") == [""]
    assert [r["status"] for r in await _interactions(manager, user_id)] == ["resolved", "failed"]


async def test_each_question_is_bracketed_by_the_callbacks(manager: UserDataManager) -> None:
    events: list[str] = []
    await _ask(manager, stdin="Lisbon\n",
               on_interaction_start=lambda: events.append("start"),
               on_interaction_end=lambda: events.append("end"))
    # Two questions: one answered, one met with end of input; each one paired.
    assert events == ["start", "end", "start", "end"]
