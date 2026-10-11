from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BLUE_DATA_USER_SOURCE_", env_file=".env", extra="ignore")

    data_dir: Path = Path("~/.blue-userdb").expanduser()
    api_key: str = ""
    schema_path: str = ""
    metadata_schema_path: str = ""
    contact_schema_path: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    # Extra browser origins allowed to make state-changing requests, comma
    # separated (e.g. a UI served from another host). The API's own origin is
    # always allowed; see the cross-origin guard in app.py (#139).
    allowed_origins: str = ""


settings = Settings()
