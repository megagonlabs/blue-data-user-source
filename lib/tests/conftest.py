import sys
from pathlib import Path

# llama_index is not installed in this environment; load the stub.
sys.path.insert(0, str(Path(__file__).parent / "stubs"))

import pytest

from blue_data_user_source.data.manager import StoreFactory, UserDataManager
from blue_data_user_source.data.registry import UserDataRegistry
from blue_data_user_source.interfaces import GraphSource, VectorSource
from tests.doubles.sources import InMemoryGraphSource, InMemoryVectorSource


def _in_memory_store_factory(name: str) -> tuple[GraphSource, VectorSource]:
    return InMemoryGraphSource(), InMemoryVectorSource()


@pytest.fixture
def store_factory() -> StoreFactory:
    return _in_memory_store_factory


@pytest.fixture
def graph_store() -> InMemoryGraphSource:
    return InMemoryGraphSource()


@pytest.fixture
def vector_store() -> InMemoryVectorSource:
    return InMemoryVectorSource()


@pytest.fixture
def user_id() -> str:
    return "test-user-001"


@pytest.fixture
async def registry(
    graph_store: InMemoryGraphSource, vector_store: InMemoryVectorSource
) -> UserDataRegistry:
    reg = UserDataRegistry(graph_store, vector_store)
    await reg.register_source("test-user-001:graph", graph_store)
    await reg.register_source("test-user-001:vector", vector_store)
    return reg


@pytest.fixture
async def data_manager(user_id: str, store_factory: StoreFactory) -> UserDataManager:
    mgr = UserDataManager(store_factory=store_factory)
    await mgr.create_user(user_id)
    return mgr
