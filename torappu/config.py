from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    backend_endpoint: str | None = None

    sentry_dsn: str | None = None

    def is_production(self):
        return self.environment == "production"
