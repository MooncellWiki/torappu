from ipaddress import IPv4Address
from pathlib import Path
from typing import Literal

from pydantic import Field, IPvAnyAddress
from pydantic_settings import BaseSettings, SettingsConfigDict

from torappu.consts import WINDOWS


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="allow",
    )

    environment: Literal["production", "debug"] = "debug"

    host: IPvAnyAddress = IPv4Address("0.0.0.0")  # type: ignore
    port: int = Field(default=8080, ge=1, le=65535)
    log_level: int | str = "INFO"
    max_workers: int = 2

    token: str = ""
    timeout: int = 10

    backend_endpoint: str = ""
    flatc_path: Path = Path("bin/flatc.exe" if WINDOWS else "bin/flatc")

    wiki_username: str = ""
    wiki_password: str = ""

    sentry_dsn: str = (
        "https://bdbb1f368fbc5bc44dd1eaf1ede0e0df@ingest.sentry.mooncell.wiki/4508025601064960"
    )

    def is_production(self):
        return self.environment == "production"
