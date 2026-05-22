from blue_data_user_source.data.manager import StoreFactory, UserDataManager
from blue_data_user_source.interfaces import DataSource
from blue_data_user_source.reasoning import UserQueryReasoner
from blue_data_user_source.types import ImportError, QueryError, QueryResult


class UserSource:
    """Entry point for all UserDb operations."""

    def __init__(self, properties: dict[str, object] | None = None) -> None:
        props = properties or {}
        self._default_database: str | None = str(props["database"]) if "database" in props else None
        store_factory: StoreFactory | None = props.get("store_factory")  # type: ignore[assignment]
        schema_path: str | None = str(props["schema_path"]) if "schema_path" in props else None
        self._data_manager = UserDataManager(store_factory=store_factory, schema_path=schema_path)

    async def execute_query(
        self,
        query: str,
        database: str | None = None,
        optional_properties: dict[str, object] | None = None,
    ) -> list[QueryResult] | str:
        """Execute a natural language query against a user database.

        optional_properties:
          session     – session identifier string
          output_form – "json" (default) returns list[QueryResult];
                        "nl" returns a single natural language string
        """
        db = self._resolve_database(database)
        props = optional_properties or {}
        session_id = str(props["session"]) if "session" in props else None
        output_form = str(props.get("output_form", "json"))
        top_k = int(props["top_k"]) if "top_k" in props else 10
        threshold = float(props["threshold"]) if "threshold" in props else None

        reasoner = UserQueryReasoner(source=self, database=db, session_id=session_id)

        print(f"Original query: {query}")
        rewritten = await reasoner.contextualize_query(query)
        print(f"Rewritten query: {rewritten}")
        questions = await reasoner.expand_query(rewritten)
        print(f"Expanded questions: {questions}")

        questions.append(rewritten)  # Ensure the original (rewritten) query is included as a fallback

        results: list[QueryResult] = []
        for question in questions:
            data, metadata = await self._data_manager.execute_query(question, db, top_k=top_k, threshold=threshold)
            metrics = await reasoner.assess_query_results(question, data, metadata)
            needs_interaction = await reasoner.assess_user_verification(question, data, metadata, metrics)

            if needs_interaction:
                data, metadata = await reasoner.request_user_clarification(question, data, metadata, metrics)

            results.append(QueryResult(query=question, results=data))

        if output_form == "nl":
            return await reasoner.synthesize_results_nl(query, results)
        return results

    async def import_source(
        self,
        source: DataSource,
        database: str | None = None,
        optional_properties: dict[str, object] | None = None,
    ) -> None:
        """Import data from an external source into the user database."""
        db = self._resolve_database(database)
        props = optional_properties or {}
        queries: list[str] | None = None
        if "queries" in props:
            raw = props["queries"]
            if isinstance(raw, list):
                queries = [str(q) for q in raw]

        await self._data_manager.import_source(source, db, queries)

    async def create_database(self, name: str) -> None:
        """Create a new user database and collect initial data via onboarding."""
        await self._data_manager.create_user(name)
        await self._onboard_user(name)

    async def create_user(self, name: str) -> None:
        """Alias for create_database."""
        await self.create_database(name)

    async def _onboard_user(self, database: str) -> None:
        """Ask schema-driven questions and store answers to seed a new user database."""
        from blue_data_user_source.interaction import ContactManager

        questions = await self._data_manager._llm_onboarding_questions()
        if not questions:
            return

        contact_manager = ContactManager(database=database, data_manager=self._data_manager)
        channel = await contact_manager.identify_contact_method("onboarding")
        interaction = channel.interact()

        await interaction.start()
        for question in questions:
            response = await interaction.send(question)
            schema = await self._data_manager._llm_extract_schema(question)
            extracted, sources = await self._data_manager._llm_extract_data(question, schema, [str(response)])
            for key, values in extracted.items():
                await self._data_manager.store_data(database, key, values, source_text=sources.get(key))
        await interaction.stop()

    async def list_data(
        self,
        database: str | None = None,
        key: str | None = None,
    ) -> list[dict]:
        """Return data entries for the database, optionally filtered by attribute key name."""
        db = self._resolve_database(database)
        return await self._data_manager.list_data(db, key)

    async def list_metadata(
        self,
        database: str | None = None,
        source_id: str | None = None,
    ) -> list[dict]:
        """Return source metadata entries for the database, optionally filtered by source_id."""
        db = self._resolve_database(database)
        return await self._data_manager.list_metadata(db, source_id)

    async def describe_data(
        self,
        database: str | None = None,
        key: str | None = None,
    ) -> str:
        """Return a natural language description of data entries for the database."""
        db = self._resolve_database(database)
        entries = await self._data_manager.list_data(db, key)
        reasoner = UserQueryReasoner(source=self, database=db)
        return await reasoner.synthesize_data_nl(entries)

    async def describe_metadata(
        self,
        database: str | None = None,
        source_id: str | None = None,
    ) -> str:
        """Return a natural language description of source metadata for the database."""
        db = self._resolve_database(database)
        entries = await self._data_manager.list_metadata(db, source_id)
        reasoner = UserQueryReasoner(source=self, database=db)
        return await reasoner.synthesize_metadata_nl(entries)

    def _resolve_database(self, database: str | None) -> str:
        db = database or self._default_database
        if db is None:
            raise QueryError("No database specified and no default configured.")
        return db
