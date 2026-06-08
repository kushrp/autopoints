from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    amadeus_client_id: str = ""
    amadeus_client_secret: str = ""
    amadeus_hostname: str = "test"

    # Browserbase: required for the AlaskaProvider (and future Browserbase-driven
    # direct providers). Empty values mean the provider raises ProviderError at
    # invocation rather than at process start, so users without Browserbase keys
    # can still run autopoints in cash-only mode.
    browserbase_api_key: str = ""
    browserbase_project_id: str = ""

    autopoints_cache_path: Path = Field(
        default_factory=lambda: Path.home() / ".autopoints" / "cache.db"
    )
    autopoints_cpp_great: float = 2.0
    autopoints_cpp_good: float = 1.5

    def cache_path(self) -> Path:
        self.autopoints_cache_path.parent.mkdir(parents=True, exist_ok=True)
        return self.autopoints_cache_path


settings = Settings()
