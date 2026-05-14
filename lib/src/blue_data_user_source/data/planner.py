from dataclasses import dataclass

from blue_data_user_source.interfaces import DataPlanner
from blue_data_user_source.data.registry import UserDataRegistry


@dataclass
class SubqueryPlan:
    """A single step in a query execution plan."""

    subquery: str
    source_id: str


class UserDataPlanner(DataPlanner):
    """Decomposes a query into subqueries mapped to relevant sources."""

    def __init__(self, registry: UserDataRegistry) -> None:
        self._registry = registry

    async def plan(self, query: str, database: str) -> list[SubqueryPlan]:
        """Return an execution plan for query against the given user database."""
        json_source_id = f"{database}:json"
        vector_source_id = f"{database}:vector"

        # Emit one subquery per generic store; registered user-specific sources
        # would be appended here once the registry exposes source enumeration.
        return [
            SubqueryPlan(subquery=query, source_id=vector_source_id),
            SubqueryPlan(subquery=query, source_id=json_source_id),
        ]
