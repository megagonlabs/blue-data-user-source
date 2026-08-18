from __future__ import annotations

from blue_data_user_source.data.manager import CLS_JSON_FILE
from blue_data_user_source.source import UserSource


class FileUserSource(UserSource):
    """File-backed UserSource — registry persisted as a JSON file.

    ``connection.path`` names the registry file (default: ``registry.json``).
    The same path is used for ``properties["registry"]`` so it is captured
    when the source is stored and reconstructed via ``DataSource.instantiate``.

    Protocol: ``user/file``

    Example::

        FileUserSource("us", {"connection": {"path": "~/.udb/registry.json"}})
    """

    def __init__(self, name: str = "user_source", properties: dict | None = None) -> None:
        props = dict(properties or {})
        if not props.get("registry"):
            conn = props.get("connection") or {}
            path = conn.get("path", "registry.json")
            props["registry"] = {
                "_class": CLS_JSON_FILE,
                "connection": {"protocol": "json/file", "path": path},
            }
        super().__init__(name, props)

    def _initialize_connection_properties(self) -> None:
        super()._initialize_connection_properties()
        conn = self.properties["connection"]
        conn["protocol"] = "user/file"
        conn.setdefault("path", "registry.json")
