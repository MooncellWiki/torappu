from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    environment: str = "prod"

    token: str = ""
    backend_endpoint: str = ""

    wiki_username: str = ""
    wiki_password: str = ""

    sentry_dsn: str = Field(
        default="https://a743fee458854a24b86356cb8520a975@ingest.sentry.mooncell.wiki/9"
    )
