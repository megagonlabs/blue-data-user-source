from pathlib import Path
from typing import Any


class FileSource:
    """Reads a plain-text file and returns its lines as query results."""

    source_type = "file"

    def __init__(self, path: str | Path) -> None:
        self.location = str(path)
        self._path = Path(path)

    async def query(self, query: str) -> list[Any]:
        return self._path.read_text().splitlines()
