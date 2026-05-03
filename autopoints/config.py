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

    autopoints_cache_path: Path = Field(
        default_factory=lambda: Path.home() / ".autopoints" / "cache.db"
    )
    autopoints_cpp_great: float = 2.0
    autopoints_cpp_good: float = 1.5

    def cache_path(self) -> Path:
        self.autopoints_cache_path.parent.mkdir(parents=True, exist_ok=True)
        return self.autopoints_cache_path


settings = Settings()
