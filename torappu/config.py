from ipaddress import IPv4Address
from pathlib import Path
from typing import Literal

from pydantic import Field, IPvAnyAddress
from pydantic_settings import BaseSettings, SettingsConfigDict

from torappu.consts import MACOS, WINDOWS


def get_flatc_path():
    if WINDOWS:
        return Path("bin/flatc.exe")
    elif MACOS:
        return Path("bin/macos/flatc")
    else:
        return Path("bin/flatc")


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

    token: str | None = None
    timeout: int = 10

    backend_endpoint: str | None = None
    flatc_path: Path = get_flatc_path()

    sentry_dsn: str | None = None

    def is_production(self):
        return self.environment == "production"
