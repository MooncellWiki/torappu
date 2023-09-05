from pathlib import Path
from ipaddress import IPv4Address

from pydantic import IPvAnyAddress
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    environment: str = "dev"

    host: IPvAnyAddress = IPv4Address("0.0.0.0")  # type: ignore
    token: str = ""
    timeout: int = 10

    backend_endpoint: str = ""
    flatc_path: Path = Path("flatc")

    wiki_username: str = ""
    wiki_password: str = ""

    sentry_dsn: str = (
        "https://a743fee458854a24b86356cb8520a975@ingest.sentry.mooncell.wiki/9"
    )
