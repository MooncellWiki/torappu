from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from torappu.consts import BASE_DIR


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="allow",
    )

    environment: Literal["production", "debug"] = "debug"

    log_level: int | str = "DEBUG"

    token: str | None = None
    timeout: int = 10

    max_concurrent_downloads: int = 16

    backend_endpoint: str | None = None

    sentry_dsn: str | None = None

    # Filesystem layout. Defaults anchor to the repository root (what the
    # editable install and the Docker image use); override via STORAGE_DIR /
    # FBS_DIR / ASSETS_DIR or constructor kwargs when torappu is installed as a
    # wheel or embedded as a library.
    storage_dir: Path = BASE_DIR / "storage"
    fbs_dir: Path = BASE_DIR / "OpenArknightsFBS" / "FBS"
    assets_dir: Path = BASE_DIR / "assets"

    @field_validator("storage_dir", "fbs_dir", "assets_dir")
    @classmethod
    def _expand_user(cls, value: Path) -> Path:
        return value.expanduser()

    @property
    def assetbundle_dir(self) -> Path:
        return self.storage_dir / "assetbundle"

    @property
    def hot_update_list_dir(self) -> Path:
        return self.storage_dir / "hot_update_list"

    @property
    def gamedata_dir(self) -> Path:
        return self.storage_dir / "asset" / "gamedata"

    @property
    def raw_dir(self) -> Path:
        return self.storage_dir / "asset" / "raw"

    def is_production(self):
        return self.environment == "production"
