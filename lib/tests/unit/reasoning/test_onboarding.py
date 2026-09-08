"""Tests for UserQueryReasoner.onboard and its supporting helpers."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.reasoning.reasoner import UserQueryReasoner
from blue_data_user_source.types import QueryError

_METADATA_SCHEMA = str(
    Path(__file__).parent.parent.parent.parent
    / "src" / "blue_data_user_source" / "data" / "metadata_schema.json"
)


@pytest.fixture
def reasoner(manager: UserDataManager) -> UserQueryReasoner:
    return UserQueryReasoner(source=MagicMock(), manager=manager)


def _mock_contact_manager(responses: list[str]) -> AsyncMock:
    mock_interaction = AsyncMock()
    mock_interaction.send = AsyncMock(side_effect=list(responses))

    mock_method = MagicMock()
    mock_method.protocol = "stdio"
    mock_method.name = "default"
    mock_method.interact.return_value = mock_interaction

    mock_cm = AsyncMock()
    mock_cm.identify_contact_method = AsyncMock(return_value=mock_method)
    return mock_cm


# ── onboard: top-level orchestration ──────────────────────────────────────────

async def test_onboard_raises_without_manager() -> None:
    reasoner = UserQueryReasoner(source=MagicMock(), manager=None)
    with pytest.raises(QueryError):
        await reasoner.onboard()


async def test_onboard_no_op_when_no_questions_generated(reasoner: UserQueryReasoner) -> None:
    reasoner._manager.set_metadata("identity.name", "Alice Smith")
    with (
        patch.object(reasoner, "_generate_kb_onboarding_questions", AsyncMock(return_value=[])),
        patch.object(reasoner, "_generate_metadata_onboarding_questions", AsyncMock(return_value=[])),
        patch("blue_data_user_source.interaction.ContactManager") as mock_cm_cls,
    ):
        await reasoner.onboard()
    mock_cm_cls.assert_not_called()


async def test_onboard_asks_fixed_name_question_first(reasoner: UserQueryReasoner) -> None:
    async def fake_llm_complete(prompt: str, **kwargs):
        if "Extract the value of" in prompt:
            return {"value": "they/them"}
        if "user profile fields" in prompt:
            return {"questions": [{"key": "identity.pronouns", "question": "What are your pronouns?"}]}
        return {"questions": ["What is your nationality?"]}

    mock_store = AsyncMock()
    mock_cm = _mock_contact_manager(["Alice Smith", "American", "they/them"])

    with (
        patch("blue_data_user_source.reasoning.reasoner._llm_complete", fake_llm_complete),
        patch("blue_data_user_source.interaction.ContactManager", return_value=mock_cm),
        patch.object(reasoner._manager, "store_data", mock_store),
    ):
        await reasoner.onboard(metadata_schema_path=_METADATA_SCHEMA)

    mock_cm.identify_contact_method.assert_awaited_once_with(topic="onboarding")
    assert reasoner._manager.get_metadata("identity.name") == "Alice Smith"
    assert reasoner._manager.get_metadata("identity.pronouns") == "they/them"
    mock_store.assert_any_await(
        "Question: What is your first and last name?\nUser Response: Alice Smith\n"
        "(First name: Alice; Last name: Smith)",
        queries=[
            "What is the user's first name?",
            "What is the user's last name?",
            "What is the user's full name?",
        ],
    )
    mock_store.assert_any_await(
        "Question: What is your nationality?\nUser Response: American",
        queries=["What is your nationality?"],
    )


async def test_onboard_skips_name_question_when_already_set(reasoner: UserQueryReasoner) -> None:
    reasoner._manager.set_metadata("identity.name", "Alice Smith")

    async def fake_llm_complete(prompt: str, **kwargs):
        return {"questions": ["What is your nationality?"]}

    mock_store = AsyncMock()
    mock_cm = _mock_contact_manager(["American"])

    with (
        patch("blue_data_user_source.reasoning.reasoner._llm_complete", fake_llm_complete),
        patch("blue_data_user_source.interaction.ContactManager", return_value=mock_cm),
        patch.object(reasoner._manager, "store_data", mock_store),
    ):
        await reasoner.onboard(metadata_schema_path=_METADATA_SCHEMA)

    mock_store.assert_awaited_once_with(
        "Question: What is your nationality?\nUser Response: American",
        queries=["What is your nationality?"],
    )
    assert reasoner._manager.get_metadata("identity.name") == "Alice Smith"


async def test_onboard_skips_metadata_set_when_name_not_answered(
    reasoner: UserQueryReasoner,
) -> None:
    async def fake_llm_complete(prompt: str, **kwargs):
        return {"questions": []}

    mock_cm = _mock_contact_manager([""])

    with (
        patch("blue_data_user_source.reasoning.reasoner._llm_complete", fake_llm_complete),
        patch("blue_data_user_source.interaction.ContactManager", return_value=mock_cm),
    ):
        await reasoner.onboard(metadata_schema_path=_METADATA_SCHEMA)

    assert reasoner._manager.get_metadata("identity.name") is None


async def test_onboard_skips_storing_when_no_response(reasoner: UserQueryReasoner) -> None:
    async def fake_llm_complete(prompt: str, **kwargs):
        return {"questions": ["What is your nationality?"]}

    mock_interaction = AsyncMock()
    mock_interaction.send = AsyncMock(return_value="")
    mock_method = MagicMock()
    mock_method.protocol = "stdio"
    mock_method.name = "default"
    mock_method.interact.return_value = mock_interaction
    mock_cm = AsyncMock()
    mock_cm.identify_contact_method = AsyncMock(return_value=mock_method)

    mock_store = AsyncMock()
    with (
        patch("blue_data_user_source.reasoning.reasoner._llm_complete", fake_llm_complete),
        patch("blue_data_user_source.interaction.ContactManager", return_value=mock_cm),
        patch.object(reasoner._manager, "store_data", mock_store),
    ):
        await reasoner.onboard()
    mock_store.assert_not_awaited()


# ── _generate_kb_onboarding_questions ─────────────────────────────────────────

async def test_generate_kb_onboarding_questions_uses_person_attributes(
    reasoner: UserQueryReasoner,
) -> None:
    captured: dict = {}

    async def fake_llm_complete(prompt: str, **kwargs):
        captured["prompt"] = prompt
        return {"questions": ["What is your nationality?"]}

    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", fake_llm_complete):
        result = await reasoner._generate_kb_onboarding_questions()

    assert result == ["What is your nationality?"]
    marker = "covering only the following attributes: "
    attrs = captured["prompt"].split(marker, 1)[1].split(".\n", 1)[0].split(", ")
    assert "NATIONALITY" in attrs
    assert "NICK_NAME" in attrs  # only exact NAME/FIRST_NAME/LAST_NAME are excluded
    assert "NAME" not in attrs
    assert "FIRST_NAME" not in attrs
    assert "LAST_NAME" not in attrs


async def test_generate_kb_onboarding_questions_caps_at_five(reasoner: UserQueryReasoner) -> None:
    questions = [f"question {i}" for i in range(8)]
    with patch(
        "blue_data_user_source.reasoning.reasoner._llm_complete",
        AsyncMock(return_value={"questions": questions}),
    ):
        result = await reasoner._generate_kb_onboarding_questions()
    assert result == questions[:5]


async def test_generate_kb_onboarding_questions_empty_when_schema_export_fails(
    reasoner: UserQueryReasoner,
) -> None:
    with patch.object(
        reasoner._manager._ensure_kb_source(), "export_database_schema",
        AsyncMock(side_effect=Exception("boom")),
    ):
        result = await reasoner._generate_kb_onboarding_questions()
    assert result == []


# ── _generate_metadata_onboarding_questions ───────────────────────────────────

async def test_generate_metadata_onboarding_questions_skips_already_set_keys(
    reasoner: UserQueryReasoner,
) -> None:
    reasoner._manager.set_metadata("identity.name", "Alice")
    captured: dict = {}

    async def fake_llm_complete(prompt: str, **kwargs):
        captured["prompt"] = prompt
        return {"questions": [{"key": "identity.pronouns", "question": "What are your pronouns?"}]}

    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", fake_llm_complete):
        result = await reasoner._generate_metadata_onboarding_questions(_METADATA_SCHEMA)

    assert "identity.name" not in captured["prompt"]
    assert "identity.pronouns" in captured["prompt"]
    assert result == [
        {"key": "identity.pronouns", "question": "What are your pronouns?", "type": "str"}
    ]


async def test_generate_metadata_onboarding_questions_always_excludes_identity_name(
    reasoner: UserQueryReasoner,
) -> None:
    """identity.name is covered by the fixed name question, even while still unset."""
    captured: dict = {}

    async def fake_llm_complete(prompt: str, **kwargs):
        captured["prompt"] = prompt
        return {"questions": [{"key": "identity.pronouns", "question": "What are your pronouns?"}]}

    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", fake_llm_complete):
        await reasoner._generate_metadata_onboarding_questions(_METADATA_SCHEMA)

    assert reasoner._manager.get_metadata("identity.name") is None
    assert "identity.name" not in captured["prompt"]


async def test_generate_metadata_onboarding_questions_filters_unknown_keys(
    reasoner: UserQueryReasoner,
) -> None:
    async def fake_llm_complete(prompt: str, **kwargs):
        return {"questions": [{"key": "not.a.real.key", "question": "???"}]}

    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", fake_llm_complete):
        result = await reasoner._generate_metadata_onboarding_questions(_METADATA_SCHEMA)

    assert result == []


async def test_generate_metadata_onboarding_questions_empty_without_schema_path(
    reasoner: UserQueryReasoner,
) -> None:
    result = await reasoner._generate_metadata_onboarding_questions(None)
    assert result == []


# ── _extract_metadata_value ───────────────────────────────────────────────────

async def test_extract_metadata_value_returns_llm_value(reasoner: UserQueryReasoner) -> None:
    with patch(
        "blue_data_user_source.reasoning.reasoner._llm_complete",
        AsyncMock(return_value={"value": "they/them"}),
    ):
        value = await reasoner._extract_metadata_value(
            {"key": "identity.pronouns", "type": "str"}, "I go by they/them"
        )
    assert value == "they/them"


async def test_extract_metadata_value_returns_none_on_non_dict_response(
    reasoner: UserQueryReasoner,
) -> None:
    with patch(
        "blue_data_user_source.reasoning.reasoner._llm_complete",
        AsyncMock(return_value="not json"),
    ):
        value = await reasoner._extract_metadata_value(
            {"key": "identity.pronouns", "type": "str"}, "whatever"
        )
    assert value is None
