from __future__ import annotations

from pathlib import Path

import pytest

from blue_data_user_source.data.manager import (
    CLS_JSON_MEMORY,
    CLS_KB_MEMORY,
    UserDataManager,
)

_SRC = Path(__file__).parent.parent / "src" / "blue_data_user_source" / "data"
_SCHEMA         = str(_SRC / "schema.json")
_METADATA_SCHEMA = str(_SRC / "metadata_schema.json")
_CONTACT_SCHEMA  = str(_SRC / "contact_schema.json")

_MEM_JSON = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
_MEM_KB   = {"_class": CLS_KB_MEMORY,   "connection": {"protocol": "kb/memory"}}


@pytest.fixture
def user_id() -> str:
    return "test-user-001"


@pytest.fixture
async def manager(user_id: str) -> UserDataManager:
    """Fully built UserDataManager with all-memory sources."""
    mgr = UserDataManager(user_id, _MEM_JSON)
    await mgr.build(
        schema_path=_SCHEMA,
        kb_source_props=_MEM_KB,
        metadata_schema_path=_METADATA_SCHEMA,
        metadata_source_props=_MEM_JSON,
        contact_schema_path=_CONTACT_SCHEMA,
        contact_source_props=_MEM_JSON,
    )
    return mgr
