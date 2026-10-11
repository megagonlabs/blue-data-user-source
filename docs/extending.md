# Extending blue-data-user-source

`UserSource` itself has no plugin/hook mechanism for the reasoning or data-management logic — query rewriting, expansion, metric evaluation, and the interaction loop are fixed. The things this library is designed to have swapped out are the **outer registry backend**, the **per-user knowledge-graph backend**, the **contact method protocols**, and the **document-store embedding/vector backend**. This page covers each, plus what to know if you want to change how LLM calls are made.

## Implementing a new outer registry backend

`UserSource` subclasses fill in `properties["registry"]` (a `blue-data` `JSONSource` config) from their own constructor arguments. The three shipped backends are the reference implementations:

```python
from blue_data_user_source.source import UserSource
from blue_data_user_source.data.manager import CLS_JSON_FILE

class MyUserSource(UserSource):
    """<Backend>-backed UserSource — registry stored in <backend>."""

    def __init__(self, name: str = "user_source", properties: dict | None = None) -> None:
        props = dict(properties or {})
        if not props.get("registry"):
            conn = props.get("connection") or {}
            props["registry"] = {
                "_class": "mypackage.my_json_source.MyJSONSource",
                "connection": {"protocol": "json/my_backend", **conn},
            }
        super().__init__(name, props)

    def _initialize_connection_properties(self) -> None:
        super()._initialize_connection_properties()
        self.properties["connection"]["protocol"] = "user/my_backend"
```

`FileUserSource` (`lib/src/blue_data_user_source/file_user_source.py`) and `RedisUserSource` (`lib/src/blue_data_user_source/redis/redis_user_source.py`) are the templates to read alongside this — the pattern is: normalize `properties["connection"]` into a `properties["registry"]` `JSONSource` config the first time, then override `_initialize_connection_properties` to report your own `user/*` protocol. The actual `JSONSource` implementation (`MyJSONSource` above) comes from `blue-data` — see that repository if you need a genuinely new key-value backend, not just a new `UserSource` wrapper around an existing one.

Once implemented, `DataSource.instantiate("mypackage.MyUserSource", "name", properties=...)` can construct it dynamically from a config-driven backend choice, the same mechanism the CLI, MCP server, and REST API use internally when reconnecting a stored user record.

---

## Choosing a per-user knowledge-graph backend

Each user's `"kb"` source is a `blue_data_kb_source.kb_source.KBSource` mixin, selected at `create_user`/`build` time via `kb_source_props["_class"]` — this library never imports a concrete KB backend directly. The three backends `blue-data-kb-source` ships (`MemoryKBSource`, `FileKBSource`, `NEO4JKBSource`) all work here unmodified; see [`blue-data-kb-source`'s extending.md](https://github.com/megagon-internal/blue-data-kb-source/blob/1.0/docs/extending.md) for implementing a genuinely new one. Class paths this library recognizes as legacy shorthand (`data/manager.py`'s `_KB_BACKENDS`):

```python
CLS_KB_MEMORY = "blue_data_kb_source.memory_kb_source.MemoryKBSource"
CLS_KB_FILE   = "blue_data_kb_source.file_kb_source.FileKBSource"
CLS_KB_NEO4J  = "blue_data_kb_source.neo4j.neo4j_kb_source.NEO4JKBSource"
```

Any other `KBSource` subclass works too — pass its dotted path directly as `kb_source_props["_class"]`; the legacy `{"backend": "memory"|"file"|"neo4j"}` shorthand only resolves those three.

---

## Adding a contact method protocol

Contact methods are dispatched by `protocol` string inside `ContactMethod.interact()` (`lib/src/blue_data_user_source/interaction/contact.py`) — there's no registry of protocol classes to subclass. Adding a new one means adding a branch:

```python
def interact(self, interaction_id: str | None = None) -> InteractionManager:
    if self.protocol == "stdio":
        return self._stdio_manager(interaction_id)
    if self.protocol == "webhook":
        return self._webhook_manager(interaction_id)
    if self.protocol == "email":
        return self._email_manager(interaction_id)
    if self.protocol == "my_protocol":
        return self._my_protocol_manager(interaction_id)
    raise InteractionError(f"Unsupported protocol: {self.protocol}")
```

Each `_*_manager` method builds an `InteractionManager(on_start, on_response, on_stop)` closing over whatever state the protocol needs (an HTTP client, an SMTP connection, a `Future` registered in the shared `pending_interactions` dict for async correlation — see `interaction/pending.py`). `stdio` is the simplest reference (`_stdio_manager`, prints and reads stdin synchronously, no `interaction_id` correlation needed); `_webhook_manager` is the template for an async request/response protocol correlated by `interaction_id`.

To make the new protocol's detail keys self-describing in the CLI (`blue-userdb contact add/set/list`) and any tooling that reads it, add an entry to `lib/src/blue_data_user_source/data/contact_schema.json` following the existing shape (`__description__` plus one entry per field with `description`/`type`/`required`/`default`).

If the protocol needs an inbound reply channel like email's (a webhook payload from a third-party provider that must resolve a pending `Future`), model it after `interaction/email/adapter.py`'s `InboundEmailAdapter` ABC and its `mailgun.py`/`postmark.py`/`sendgrid.py` implementations, each parsing one provider's webhook payload shape and calling back into the REST API's `POST /interactions/email/inbound` handler (`platform/api/src/blue_data_user_api/`).

---

## Choosing the document-store embedding/vector backend

`session_content` and `external_documents` are `blue_data_doc_source.DocumentDataSource`s configured once per user via `doc_source_props` at `create_user` time:

```python
doc_source_props={
    "embedding_model": "dummy",   # or "openai"
    "vector_source": {"backend": "memory", "directory": "..."},   # or "file"
}
```

`data/manager.py`'s `_build_embedding_model` is the only place that resolves the `embedding_model` string — currently `"dummy"` (`DummyEmbeddingModel`, no network calls) and `"openai"` (`OpenAIEmbeddingModel`) from `blue-data-doc-source`. A new embedding provider means adding a branch there; a new vector backend is a `blue-data` `VectorSource` implementation passed the same way `blue-data-kb-source` accepts one (see [that repo's extending.md](https://github.com/megagon-internal/blue-data-kb-source/blob/1.0/docs/extending.md#implementing-a-new-vectorsource-backend)) — this library doesn't reconnect these sources through the generic registry `_class`/`connection` path (a live embedding-model object can't round-trip through that), so a new backend choice has to be added to `_build_embedding_model`/the vector-source construction in `data/manager.py` directly, not just registered externally.

---

## Swapping the LLM provider

`reasoning/reasoner.py` and `reasoning/metric.py` call the OpenAI SDK directly (`from openai import AsyncOpenAI`, via a shared `_llm_complete` helper) — there is no provider-agnostic abstraction layer in the current code, despite an earlier design sketch ([`design/05-software-stack.md`](../design/05-software-stack.md)) proposing a LlamaIndex `LLM` abstraction; that was never implemented.

To use a different provider today, `_llm_complete` in `reasoner.py` is the single choke point for reasoning-layer LLM calls — it takes a plain prompt string and an optional `properties={"response_format": "json_object"}` and returns a string or parsed dict. Changing its internals to call a different provider doesn't ripple into `UserQueryReasoner`'s or `UserDataMetric`'s own logic, since they only ever call through it. Keep the same return contract (plain string, or a JSON-parseable dict when `response_format: "json_object"` is requested) since prompt construction and result parsing throughout the reasoning layer assume it.
