import sys
from pathlib import Path

# llama_index is not installed in this environment; load the stub.
sys.path.insert(0, str(Path(__file__).parent / "stubs"))

import pytest

from blue_data_user_source.data.manager import StoreFactory, UserDataManager
from blue_data_user_source.data.registry import UserDataRegistry
from blue_data_user_source.interfaces import JSONSource, VectorSource
from tests.doubles.sources import InMemoryJsonSource, InMemoryVectorSource


def _in_memory_store_factory(name: str) -> tuple[JSONSource, VectorSource]:
    return InMemoryJsonSource(), InMemoryVectorSource()


@pytest.fixture
def store_factory() -> StoreFactory:
    return _in_memory_store_factory


@pytest.fixture
def json_store() -> InMemoryJsonSource:
    return InMemoryJsonSource()


@pytest.fixture
def vector_store() -> InMemoryVectorSource:
    return InMemoryVectorSource()


@pytest.fixture
def user_id() -> str:
    return "test-user-001"


@pytest.fixture
async def registry(
    json_store: InMemoryJsonSource, vector_store: InMemoryVectorSource
) -> UserDataRegistry:
    reg = UserDataRegistry(json_store, vector_store)
    await reg.register_source("test-user-001:json", json_store)
    await reg.register_source("test-user-001:vector", vector_store)
    return reg


@pytest.fixture
async def data_manager(user_id: str, store_factory: StoreFactory) -> UserDataManager:
    mgr = UserDataManager(store_factory=store_factory)
    await mgr.create_user(user_id)
    return mgr
