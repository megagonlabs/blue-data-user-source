from __future__ import annotations

from blue_data_user_source.data.manager import CLS_JSON_MEMORY
from blue_data_user_source.source import UserSource


class MemoryUserSource(UserSource):
    """In-memory UserSource — registry and all user data live in process, non-persistent.

    Useful for testing, short-lived pipelines, and development.  No connection
    parameters are required.

    Protocol: ``user/memory``
    """

    def __init__(self, name: str = "user_source", properties: dict | None = None) -> None:
        props = dict(properties or {})
        if not props.get("registry"):
            props["registry"] = {
                "_class": CLS_JSON_MEMORY,
                "connection": {"protocol": "json/memory"},
            }
        super().__init__(name, props)

    def _initialize_connection_properties(self) -> None:
        super()._initialize_connection_properties()
        self.properties["connection"]["protocol"] = "user/memory"
