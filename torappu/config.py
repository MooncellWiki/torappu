from pathlib import Path
from typing import Literal
from ipaddress import IPv4Address

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
        "https://d0c1327b212bddd94bc363f8ffa99d64@ingest.sentry.mooncell.wiki/9"
    )

    def is_production(self):
        return self.environment == "production"
