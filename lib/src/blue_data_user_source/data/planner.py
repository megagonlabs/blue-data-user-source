from __future__ import annotations

from dataclasses import dataclass

from blue_data.registry.data_registry import DataRegistry


@dataclass
class SubqueryPlan:
    """A single step in a query execution plan."""

    subquery: str
    source_id: str


class UserDataPlanner:
    """Placeholder for query planning over a user's sources; not used by the query path.

    ``plan`` returns the query unchanged, once per registered source. Query
    decomposition is done by ``UserQueryReasoner.expand_query``, and every
    sub-question is answered from the same fixed stores (see
    ``UserDataManager.execute_query``). Real source selection is future work
    (#128).
    """

    def __init__(self, registry: DataRegistry) -> None:
        self._registry = registry

    async def plan(self, query: str) -> list[SubqueryPlan]:
        return [SubqueryPlan(subquery=query, source_id=name) for name in self._registry.list_sources()]
