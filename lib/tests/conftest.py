from __future__ import annotations

from pathlib import Path

import pytest

from blue_data_user_source.data.manager import UserDataManager

_SRC = Path(__file__).parent.parent / "src" / "blue_data_user_source" / "data"
_SCHEMA         = str(_SRC / "schema.json")
_METADATA_SCHEMA = str(_SRC / "metadata_schema.json")
_CONTACT_SCHEMA  = str(_SRC / "contact_schema.json")


@pytest.fixture
def user_id() -> str:
    return "test-user-001"


@pytest.fixture
async def manager(user_id: str) -> UserDataManager:
    """Fully built UserDataManager with all-memory backends."""
    mgr = UserDataManager(user_id, {"backend": "memory"})
    await mgr.build(
        schema_path=_SCHEMA,
        kb_source_props={"backend": "memory"},
        metadata_schema_path=_METADATA_SCHEMA,
        metadata_source_props={"backend": "memory"},
        contact_schema_path=_CONTACT_SCHEMA,
        contact_source_props={"backend": "memory"},
    )
    return mgr
