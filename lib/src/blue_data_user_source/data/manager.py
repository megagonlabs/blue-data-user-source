import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from llama_index.core import Settings  # type: ignore[import-untyped]

from blue_data_user_source.interfaces import DataSource, GraphSource, VectorSource
from blue_data_user_source.data.planner import UserDataPlanner
from blue_data_user_source.data.registry import UserDataRegistry
from blue_data_user_source.types import ImportError

StoreFactory = Callable[[str], tuple[GraphSource, VectorSource]]


class UserDataManager:
    """Manages all data sources for a user database through a UserDataRegistry."""

    def __init__(self, store_factory: StoreFactory | None, schema_path: str | None = None) -> None:
        self._store_factory = store_factory
        self._registries: dict[str, UserDataRegistry] = {}
        self._schema_reference = open(schema_path).read() if schema_path else ""

    async def create_user(self, name: str) -> None:
        """Initialize graph and vector stores for a new user database."""
        if self._store_factory is None:
            raise ValueError("No store_factory configured. Pass 'store_factory' in UserSource properties.")
        graph_store, vector_store = self._store_factory(name)
        registry = UserDataRegistry(graph_store, vector_store)

        await registry.register_source(f"{name}:graph", graph_store)
        await registry.register_source(f"{name}:vector", vector_store)

        self._registries[name] = registry

    async def _ensure_loaded(self, database: str) -> UserDataRegistry:
        if database not in self._registries:
            await self.create_user(database)
        return self._registries[database]

    async def execute_query(
        self,
        query: str,
        database: str,
        top_k: int = 10,
        threshold: float | None = None,
    ) -> tuple[list[Any], dict[str, Any]]:
        """Execute a query and return (results, metadata) including provenance."""
        registry = await self._ensure_loaded(database)
        planner = UserDataPlanner(registry)
        plan = await planner.plan(query, database)
        print(plan)
        aggregated: list[Any] = []
        provenance: list[dict[str, Any]] = []

        for step in plan:
            raw = await registry.execute(step.subquery, step.source_id, top_k=top_k, threshold=threshold)
            aggregated.extend(raw)
            provenance.append(
                {
                    "source": step.source_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "confidence": 1.0,
                }
            )

        metadata: dict[str, Any] = {"provenance": provenance}
        return aggregated, metadata

    async def import_source(
        self,
        source: DataSource,
        database: str,
        queries: list[str] | None = None,
    ) -> None:
        """Register a source (Type 1) or extract data from it (Type 2)."""
        registry = await self._ensure_loaded(database)
        source_id = str(uuid.uuid4())
        await registry.register_source(source_id, source)

        if queries is None:
            await self._persist_source_metadata(registry, database, source, source_id, [])
        else:
            for query in queries:
                try:
                    raw = await registry.execute(query, source_id)
                    schema = await self._llm_extract_schema(database, query)
                    extracted, sources = await self._llm_extract_data(database, query, schema, raw)
                except Exception as exc:
                    raise ImportError(f"Query over source failed: {exc}") from exc
                for entry_key, entry_values in extracted.items():
                    await self._write_data_entry(
                        registry,
                        database,
                        entry_key,
                        self._normalize_to_list(entry_values),
                        source_id,
                        source_text=sources.get(entry_key),
                    )
            await self._persist_source_metadata(registry, database, source, source_id, queries)

    async def list_data(self, database: str, key: str | None = None) -> list[dict[str, Any]]:
        """Return data entries for the database, optionally filtered by schema path key."""
        registry = await self._ensure_loaded(database)
        filters: dict[str, Any] = {"database": database}
        if key is not None:
            filters["schema_path"] = key
        nodes = await registry.query_nodes(
            labels=["ENTITY", "FACT", "LITERAL"],
            properties=filters,
        )
        return nodes

    async def list_metadata(self, database: str, source_id: str | None = None) -> list[dict[str, Any]]:
        """Return source metadata entries for the database, optionally filtered by source_id."""
        registry = await self._ensure_loaded(database)
        filters: dict[str, Any] = {"database": database}
        if source_id is not None:
            filters["source_id"] = source_id
        nodes = await registry.query_nodes(labels=["SOURCE"], properties=filters)
        return [n["properties"] for n in nodes]

    async def store_data(
        self,
        database: str,
        key: str,
        value: Any,
        source_id: str = "interaction",
        source_text: str | None = None,
    ) -> None:
        """Write a data entry to the user DB graph and vector stores."""
        registry = await self._ensure_loaded(database)
        await self._write_data_entry(
            registry, database, key, self._normalize_to_list(value), source_id, source_text=source_text
        )

    @staticmethod
    def _normalize_to_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        return [value]

    @staticmethod
    def _infer_literal_type(value: Any) -> str:
        """Infer the LITERAL type tag from a Python value."""
        import re
        if isinstance(value, bool):
            return "BOOLEAN"
        if isinstance(value, (int, float)):
            return "NUMBER"
        if isinstance(value, str) and re.match(r"\d{4}-\d{2}-\d{2}", value):
            return "DATE"
        return "STRING"

    async def _write_graph_entry(
        self,
        registry: UserDataRegistry,
        database: str,
        schema_path: str,
        value: Any,
        source_id: str,
        source_text: str | None = None,
    ) -> tuple[str, str]:
        """Create graph nodes and edges for one extracted data value.

        Returns (graph_node_id, graph_node_type) — the "primary" node that the
        corresponding vector entry should reference.

        Schema path conventions:
          entity                      → bare ENTITY
          entity.attr                 → ENTITY -[HAS_PROPERTY]-> LITERAL -[IS_VALUE_OF]-> PROPERTY
          entity.RELATION.target      → head -[RELATION]-> tail + FACT -[REPRESENTS]-> RELATION
                                         + FACT -[HAS_PROPERTY]-> LITERAL
          entity.RELATION.target.attr → same FACT + LITERAL -[IS_VALUE_OF]-> PROPERTY

        All created primary nodes (ENTITY/FACT/LITERAL) receive an
        EXTRACTED_FROM edge to an EXTRACTION node when source_text is supplied.
        """
        parts = schema_path.split(".")
        now = datetime.now(timezone.utc).isoformat()
        base_props: dict[str, Any] = {"database": database, "source_id": source_id}

        # ── helpers ───────────────────────────────────────────────────────────

        async def _make_entity(key: str) -> str:
            eid = f"{database}:entity:{key}"
            await registry.add_node(eid, ["ENTITY"], {
                **base_props, "key": key, "schema_path": key, "date": now,
            })
            return eid

        async def _make_property(prop_name: str) -> str:
            pid = f"{database}:property:{prop_name}"
            await registry.add_node(pid, ["PROPERTY"], {
                "name": prop_name, "database": database,
            })
            return pid

        async def _make_literal(v: Any, prop_name: str, s_path: str) -> str:
            lid = str(uuid.uuid4())
            await registry.add_node(lid, ["LITERAL"], {
                **base_props,
                "value": v,
                "type": self._infer_literal_type(v),
                "property": prop_name,
                "schema_path": s_path,
                "date": now,
            })
            # IS_VALUE_OF: LITERAL → PROPERTY
            prop_id = await _make_property(prop_name)
            await registry.add_edge(lid, prop_id, "IS_VALUE_OF")
            return lid

        async def _make_relation(rel_name: str) -> str:
            rid = f"{database}:relation:{rel_name}"
            await registry.add_node(rid, ["RELATION"], {
                "name": rel_name, "database": database,
            })
            return rid

        async def _make_extraction() -> str | None:
            if source_text is None:
                return None
            xid = str(uuid.uuid4())
            await registry.add_node(xid, ["EXTRACTION"], {
                "text": source_text,
                "database": database,
                "source_id": source_id,
            })
            return xid

        # ── path dispatch ─────────────────────────────────────────────────────

        if len(parts) == 1:
            # Bare entity
            entity_id = await _make_entity(parts[0])
            xid = await _make_extraction()
            if xid:
                await registry.add_edge(entity_id, xid, "EXTRACTED_FROM")
            return entity_id, "ENTITY"

        if len(parts) == 2:
            # entity.attr  →  ENTITY -[HAS_PROPERTY]-> LITERAL -[IS_VALUE_OF]-> PROPERTY
            entity_key, attr_name = parts
            entity_id = await _make_entity(entity_key)
            literal_id = await _make_literal(value, attr_name, schema_path)
            await registry.add_edge(entity_id, literal_id, "HAS_PROPERTY")
            xid = await _make_extraction()
            if xid:
                await registry.add_edge(literal_id, xid, "EXTRACTED_FROM")
            return literal_id, "LITERAL"

        if len(parts) == 3:
            # entity.RELATION.target
            head_key, relation_name, tail_key = parts
            head_id = await _make_entity(head_key)
            tail_id = await _make_entity(tail_key)
            # Direct entity-to-entity edge (simple graph traversal)
            await registry.add_edge(head_id, tail_id, relation_name)
            # FACT node carries provenance + optional HAS_PROPERTY values
            fact_id = str(uuid.uuid4())
            await registry.add_node(fact_id, ["FACT"], {
                **base_props,
                "relation": relation_name,
                "schema_path": schema_path,
                "date": now,
            })
            await registry.add_edge(fact_id, head_id, "HEAD")
            await registry.add_edge(fact_id, tail_id, "TAIL")
            # REPRESENTS: FACT → RELATION
            rel_id = await _make_relation(relation_name)
            await registry.add_edge(fact_id, rel_id, "REPRESENTS")
            # Value as LITERAL property of the fact
            literal_id = await _make_literal(value, "value", schema_path)
            await registry.add_edge(fact_id, literal_id, "HAS_PROPERTY")
            xid = await _make_extraction()
            if xid:
                await registry.add_edge(fact_id, xid, "EXTRACTED_FROM")
            return fact_id, "FACT"

        if len(parts) == 4:
            # entity.RELATION.target.attr  →  FACT + named LITERAL attribute
            head_key, relation_name, tail_key, attr_name = parts
            head_id = await _make_entity(head_key)
            tail_id = await _make_entity(tail_key)
            await registry.add_edge(head_id, tail_id, relation_name)
            # Stable FACT id so attr writes converge on the same fact node
            fact_id = f"{database}:fact:{head_key}:{relation_name}:{tail_key}"
            await registry.add_node(fact_id, ["FACT"], {
                **base_props,
                "relation": relation_name,
                "schema_path": f"{head_key}.{relation_name}.{tail_key}",
                "date": now,
            })
            await registry.add_edge(fact_id, head_id, "HEAD")
            await registry.add_edge(fact_id, tail_id, "TAIL")
            rel_id = await _make_relation(relation_name)
            await registry.add_edge(fact_id, rel_id, "REPRESENTS")
            # Named attribute literal
            literal_id = await _make_literal(value, attr_name, schema_path)
            await registry.add_edge(fact_id, literal_id, "HAS_PROPERTY")
            xid = await _make_extraction()
            if xid:
                await registry.add_edge(literal_id, xid, "EXTRACTED_FROM")
            return literal_id, "LITERAL"

        # Fallback: treat entire path as a bare ENTITY
        entity_id = str(uuid.uuid4())
        await registry.add_node(entity_id, ["ENTITY"], {
            **base_props,
            "key": schema_path,
            "value": value,
            "schema_path": schema_path,
            "date": now,
        })
        xid = await _make_extraction()
        if xid:
            await registry.add_edge(entity_id, xid, "EXTRACTED_FROM")
        return entity_id, "ENTITY"

    async def _write_data_entry(
        self,
        registry: UserDataRegistry,
        database: str,
        key: str,
        value: list[Any],
        source_id: str,
        source_text: str | None = None,
    ) -> None:
        """Write extracted data to the graph and vector stores.

        Each value in the list gets:
        - A graph node (ENTITY / FACT / LITERAL) derived from the schema path.
        - A vector entry that references the graph node id in its metadata.
        """
        for item in value:
            graph_node_id, graph_node_type = await self._write_graph_entry(
                registry, database, key, item, source_id, source_text=source_text
            )
            metadata: dict[str, Any] = {
                "date": datetime.now(timezone.utc).isoformat(),
                "agent": "import-agent-v1",
                "source_id": source_id,
                "graph_node_id": graph_node_id,
                "graph_node_type": graph_node_type,
            }
            if source_text is not None:
                metadata["source_text"] = source_text
            vector_key = str(uuid.uuid4())
            vector_text = f"{key}: {item}"
            await registry.set_vector(vector_key, vector_text, metadata)

    async def _llm_extract_data(self, database: str, query: str, schema: list[str], raw_content: list[Any]) -> tuple[dict[str, Any], dict[str, str]]:
        """Extract query-relevant data and the source text segment for each extracted value."""
        llm = Settings.llm
        content_str = "\n".join(str(item) for item in raw_content)
        prompt = (
            f"Extract data for each of the schema paths relevant to the following query from the content below using the schema as a guide to extract.\n"
            f"Database: {database}\n\n"
            f"Query: {query}\n\n"
            f"Schema Paths: {schema}\n\n"
            f"Content:\n```{content_str}```\n\n"
            "Instructions:\n"
            "* Use both Query and Content as context to interpret the schema paths and extract relevant data. \n"
            "* Do not return data that cannot be clearly supported by the content. \n"
            "* Be as specific as possible and do not include irrelevant information.\n"
            "* Interpret the schema paths carefully and ensure each extracted value corresponds to the correct path, following the schema path notation as below:\n"
            "** 'entity_key_value.attribute_name' for specific entity attributes, e.g. 'alice.first_name'\n"
            "** 'entity_key_value.relation_name.target_entity_key_value' for specific relations, e.g. 'alice.HAS_SKILL.python'\n"
            "** 'entity_key_value.relation_name.target_entity_key_value.relation_attribute_key' for specific relation attributes, e.g. 'alice.HAS_SKILL.python.proficiency_level'\n"
            "* Check the extracted values to make sure each value is atomic and cannot be further broken down into more specific schema entries. If it can be broken down, break it down each into specific values. \n"
            "* Return a JSON object where each key is a schema path and each value is an object with:\n"
            "**  \"values\": a JSON array of the extracted values\n"
            "**  \"source\": the verbatim excerpt from the content that the values were extracted from, potentially including the query, especially if it provides referential context.\n"
            "* If schema path refers to a entity_type (e.g. alice.HAS_SKILL.SKILL) but extraction has a specific value, e.g. 'alice.HAS_SKILL.python' return object should have as key, the specific path.\n"
            "* Double-check if source text is present for each extracted value.\n"
            "* If multiple values are extracted from different parts of the content but map to the same schema path entry, combine them into a single array under the same key and concatenate the source text with clear delimiters.\n"
            "* If no matching value is extracted, return an empty JSON object.\n\n"
        )
        response = await llm.acomplete(prompt)
        print(f"LLM response: {response}")
        result_str = str(response).strip()
        try:
            parsed = json.loads(result_str)
        except (json.JSONDecodeError, ValueError):
            return {}, {}
        values: dict[str, Any] = {}
        sources: dict[str, str] = {}
        for k, entry in parsed.items():
            if isinstance(entry, dict) and "values" in entry:
                values[k] = entry["values"]
                if "source" in entry:
                    sources[k] = entry["source"]
            else:
                values[k] = entry
        print(f"Extracted data: {json.dumps(values, indent=2)}")
        return values, sources

    async def _llm_onboarding_questions(self) -> list[str]:
        """Generate onboarding questions for a new user based on the schema."""
        if not self._schema_reference:
            return []
        llm = Settings.llm
        prompt = (
            "Generate a concise set of conversational questions to collect information "
            "about a new user, covering only the USER node attributes in the schema below.\n\n"
            f"Schema:\n{self._schema_reference}\n\n"
            "Instructions:\n"
            "* Return a JSON array of question strings. "
            "* Each question should be clear, friendly, and cover a distinct USER attribute. "
            "* Do not ask about relationships, organizations, skills, or any non-USER attributes. "
            "* Do not ask more than 5 questions."
            "* Return only the JSON array, nothing else."
        )
        response = await llm.acomplete(prompt)
        try:
            return json.loads(str(response).strip())
        except (json.JSONDecodeError, ValueError):
            return []

    async def _llm_extract_schema(self, database: str, query: str) -> list[str]:
        """Derive schema path(s) relevant to a query."""
        llm = Settings.llm
        prompt = (
            f"Extract schema paths relevant to the following query from the content below using the schema as the data to extract. Follow the instructions below.\n"
            f"Database: {database}\n"
            f"Query: {query}\n"
            f"Schema:\n{self._schema_reference}\n\n"
            "Instructions:\n"
            "* Do not return paths that are not relevant to the query. \n"
            "* Map the query to the most appropriate paths based on the schema."
            "* Be as specific as possible and do not include irrelevant information.\n"
            "* Return result JSON as a list of paths and nothing else."
            "* Additional Instructions for identifying paths:\n"
            "* If query is referring to \"you\" as a second-person pronoun, consider that as referring to the user and use database (i.e. {database}) as the key of the entity in the schema paths.\n"
            "* If query is referring to the user by name, use database (i.e. {database}) as the key of the entity in the schema paths.\n"
            "* If query is referring to another entity, use the key of that entity as the key of the entity key in the schema paths.\n"
            "* If query is referring to a generic entity type, use the type of the entity in the schema path"
            "* If query is referring to an attribute of a a specific entity return the matching entity key and entity attribute name as the path, in the format 'entity_key_value.attribute_name', e.g. alice.first_name\n"
            "* If query is referring to an attribute of a a generic entity return the matching entity type and entity attribute name as the path, in the format 'entity_type.attribute_name', e.g. PERSON.first_name\n"
            "* If query is referring to a specific relation with specific source and target entities, return matching source entity key value, relation name, and target entity key value as the path, in the format 'source_entity_key_value.relation_name.target_entity_key_value', e.g. alice.HAS_SKILL.python\n"
            "* If query is referring to a partially specific relation with specific source entity but a generic target type, return matching source entity key value, relation name, and target entity type value as the path, in the format 'source_entity_key_value.relation_name.target_entity_type', e.g. alice.HAS_SKILL.SKILL\n"
            "* If query is referrring to a specific relation attribute with specific source and target entities, return matching source entity key value and relation name and target entity key value and relation attribute key as the path, in the format 'source_entity_key_value.relation_name.target_entity_key_value.relation_attribute_key'\n"
            "* If no exact schema path matches, extend using the same conventions"
        )
        response = await llm.acomplete(prompt)
        result_str = str(response).strip()
        print(f"LLM response: {result_str}")
        try:
            parsed = json.loads(result_str)
        except (json.JSONDecodeError, ValueError):
            return []
        print(f"Extracted paths: {json.dumps(parsed, indent=2)}")
        return parsed

    async def _persist_source_metadata(
        self,
        registry: UserDataRegistry,
        database: str,
        source: DataSource,
        source_id: str,
        queries: list[str],
    ) -> None:
        node_id = f"{database}:source:{source_id}"
        properties = {
            "id": node_id,
            "source_id": source_id,
            "source_type": getattr(source, "source_type", "unknown"),
            "location": getattr(source, "location", ""),
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "queries": json.dumps(queries),
            "database": database,
        }
        await registry.add_node(node_id, ["SOURCE"], properties)
