"""Spark configuration via environment variables and .env file."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Single source of truth for the model Spark talks to.
DEFAULT_MODEL = "claude-sonnet-5-5"

# Models Anthropic has retired; requests to these always fail.
# `spark doctor` and the startup check refuse to run with them.
RETIRED_MODELS: frozenset[str] = frozenset({
    "claude-sonnet-4-20250514",  # retired June 15, 2026
})


class AgencyLevel(str, Enum):
    SUGGEST = "suggest"
    LIGHT = "light"
    FULL = "full"


class SparkSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPARK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
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

    # Phase 4: Intelligence
    daily_digest_enabled: bool = True
    weekly_digest_enabled: bool = True
    enrich_knowledge: bool = True
    learn_from_conversations: bool = True

    # LLM
    model: str = DEFAULT_MODEL
    # Reasoning effort (output_config.effort): low | medium | high | xhigh | max
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    # "between_tools" turns off up-front thinking; "adaptive" lets the model decide.
    thinking: Literal["between_tools", "adaptive"] = "between_tools"
    # "anthropic" (API key) or "claude-cli" (shell out to the Claude Code CLI)
    llm_backend: Literal["anthropic", "claude-cli"] = "anthropic"

    # Delivery
    # Print/log messages (stdout + data_dir/dry_run_messages.log) instead of sending to Telegram
    dry_run: bool = False

    @property
    def llm_configured(self) -> bool:
        """True if the selected LLM backend has what it needs to run."""
        return self.llm_backend == "claude-cli" or bool(self.anthropic_api_key)

    @property
    def dry_run_path(self) -> Path:
        return self.data_dir / "dry_run_messages.log"

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
