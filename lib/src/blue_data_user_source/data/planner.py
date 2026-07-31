from __future__ import annotations

from dataclasses import dataclass

from blue_data.registry.data_registry import DataRegistry


@dataclass
class SubqueryPlan:
    """A single step in a query execution plan."""

    subquery: str
    source_id: str


class UserDataPlanner:
    """Decomposes a query into subqueries mapped to registered sources."""

    def __init__(self, registry: DataRegistry) -> None:
        self._registry = registry

    async def plan(self, query: str) -> list[SubqueryPlan]:
        return [SubqueryPlan(subquery=query, source_id=name) for name in self._registry.list_sources()]
