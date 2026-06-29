"""Typed application settings, loaded from the environment.

All configuration comes from environment variables with safe development
defaults. No secret literals live here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Trading Platform (Phase 1)"
    log_level: str = "INFO"

    # Postgres only — no SQLite code path. Required from the environment (see
    # .env.example / docker-compose); no credential literal lives in source.
    database_url: str

    # CSV loading is constrained to resolve under this directory (anti path-traversal).
    # Default: the repo-root data/ directory, relative to this file.
    allowed_data_dir: str = str(
        (Path(__file__).resolve().parents[3] / "data").resolve()
    )

    # CORS origins allowed to call the API (the Vite dev server by default).
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def allowed_data_path(self) -> Path:
        return Path(self.allowed_data_dir).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
