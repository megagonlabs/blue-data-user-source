from __future__ import annotations

from blue_data_user_source.data.manager import CLS_JSON_REDIS
from blue_data_user_source.source import UserSource, validate_user_name


class RedisUserSource(UserSource):
    """Redis-backed UserSource — registry stored in Redis JSON.

    Connection parameters (all optional, taken from ``connection``):
    - ``host``      — Redis host (default: ``localhost``)
    - ``port``      — Redis port (default: ``6379``)
    - ``db``        — Redis database index (default: ``0``)
    - ``password``  — Redis password (default: None)
    - ``namespace`` — Key prefix for registry entries (default: source name)

    Protocol: ``user/redis``

    Requires ``redis[hiredis]`` and the RedisJSON module on the server.

    Example::

        RedisUserSource("us", {
            "connection": {"host": "redis.host", "port": 6379, "namespace": "myapp"},
        })
    """

    def __init__(self, name: str = "user_source", properties: dict | None = None) -> None:
        props = dict(properties or {})
        if not props.get("registry"):
            conn = props.get("connection") or {}
            props["registry"] = {
                "_class": CLS_JSON_REDIS,
                "connection": {
                    "protocol": "json/redis",
                    "host": conn.get("host", "localhost"),
                    "port": conn.get("port", 6379),
                    "db": conn.get("db", 0),
                    **({"password": conn["password"]} if conn.get("password") else {}),
                },
                "namespace": conn.get("namespace", name),
            }
        super().__init__(name, props)

    def _initialize_connection_properties(self) -> None:
        super()._initialize_connection_properties()
        conn = self.properties["connection"]
        conn["protocol"] = "user/redis"
        conn.setdefault("host", "localhost")
        conn.setdefault("port", 6379)
        conn.setdefault("db", 0)
        conn.setdefault("namespace", self.name)

    def default_user_props(self, name: str) -> dict[str, dict]:
        """A new user's JSON stores in this Redis, each under its own namespace.

        There is no ``kb_source`` default: blue-data-kb-source has no Redis
        backend, and an in-memory KB would lose the user's knowledge graph on
        restart while the rest persisted. Pass one (e.g. a file or Neo4j KB).
        """
        validate_user_name(name)
        registry = self.properties["registry"]
        namespace = registry.get("namespace", self.name)

        def redis_json(store: str) -> dict:
            return {
                "_class": CLS_JSON_REDIS,
                "connection": dict(registry["connection"]),
                "namespace": f"{namespace}:{name}:{store}",
            }

        return {
            "registry": redis_json("registry"),
            "metadata_source": redis_json("metadata"),
            "contact_source": redis_json("contacts"),
            "session_source": redis_json("sessions"),
        }
