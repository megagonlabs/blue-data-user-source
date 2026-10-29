from __future__ import annotations

from pathlib import Path

from blue_data.core.utils.path_utils import contain

from blue_data_user_source.data.manager import CLS_JSON_FILE, CLS_KB_FILE, _expand_user_paths
from blue_data_user_source.source import UserSource, validate_user_name


class FileUserSource(UserSource):
    """File-backed UserSource — registry persisted as a JSON file.

    ``connection.path`` names the registry file (default: ``registry.json``).
    The same path is used for ``properties["registry"]`` so it is captured
    when the source is stored and reconstructed via ``DataSource.instantiate``.
    A leading ``~`` is expanded here, so the registry file, the data directory
    and every user's default stores sit under the home directory (#171).

    Protocol: ``user/file``

    Example::

        FileUserSource("us", {"connection": {"path": "~/.blue-userdb/registry.json"}})
    """

    def __init__(self, name: str = "user_source", properties: dict | None = None) -> None:
        props = dict(properties or {})
        for key in ("connection", "registry"):
            if isinstance(props.get(key), dict):
                props[key] = _expand_user_paths(props[key])
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

    def _data_root(self) -> Path:
        """The registry file's directory: every user's files live under it (#156)."""
        return Path(self.properties["registry"]["connection"]["path"]).parent

    def default_user_props(self, name: str) -> dict[str, dict]:
        """A new user's stores as files beside the registry file.

        With the registry at ``<dir>/registry.json``: the user's registry at
        ``<dir>/registries/<name>.json``, and the KB, ``metadata.json``,
        ``contacts.json``, ``sessions.json`` and transcripts (``sessions/``)
        under ``<dir>/sources/<name>/`` — the layout the CLI and servers use.
        """
        validate_user_name(name)  # the name becomes a path (#134)
        root = self._data_root()
        # Composed with blue-data's contain(), as delete and reset check them (#156).
        base = Path(contain(contain(str(root), "sources"), name))
        registry_file = Path(contain(contain(str(root), "registries"), name, ".json"))

        def json_file(path: Path) -> dict:
            connection = {"protocol": "json/file", "path": str(path)}
            return {"_class": CLS_JSON_FILE, "connection": connection}

        return {
            "registry": json_file(registry_file),
            "kb_source": {
                "_class": CLS_KB_FILE,
                "connection": {"protocol": "kb/file", "directory": str(base)},
            },
            "metadata_source": json_file(base / "metadata.json"),
            "contact_source": json_file(base / "contacts.json"),
            "session_source": json_file(base / "sessions.json"),
            "doc_source": {
                "embedding_model": "dummy",
                "vector_source": {"backend": "file", "directory": str(base / "sessions")},
            },
        }
