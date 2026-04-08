"""Spark configuration via environment variables and .env file."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgencyLevel(str, Enum):
    SUGGEST = "suggest"
    LIGHT = "light"
    FULL = "full"


class SparkSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPARK_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Required
    anthropic_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Paths
    projects_dir: Path = Field(default_factory=lambda: Path.home() / "projects")
    knowledge_dir: Path = Field(default_factory=lambda: Path.home() / "knowledge")
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".spark")

    # Preferences
    timezone: str = "UTC"
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "08:00"
    agency_level: AgencyLevel = AgencyLevel.SUGGEST
    max_daily_nudges: int = 3

    # Tuning
    stall_check_interval_minutes: int = 30
    min_hours_between_nudges: float = 4.0
    stall_threshold_multiplier: float = 2.0

    # LLM
    model: str = "claude-sonnet-4-20250514"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "spark.db"

    @property
    def chromadb_path(self) -> Path:
        return self.data_dir / "chromadb"

    def ensure_dirs(self) -> None:
        """Create data directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> SparkSettings:
    """Load settings from environment / .env file."""
    return SparkSettings()
