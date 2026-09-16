from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BLUE_DATA_USER_SOURCE_", env_file=".env", extra="ignore")

    data_dir: Path = Path("~/.udb").expanduser()
    api_key: str = ""
    schema_path: str = ""
    metadata_schema_path: str = ""
    contact_schema_path: str = ""
    host: str = "127.0.0.1"
    port: int = 8000


settings = Settings()
