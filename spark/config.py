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
        extra="ignore",
    )

    # Required - at least one API key needed
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    llm_api_key: str = ""  # Generic fallback for any provider
    llm_api_base: str = ""  # Custom endpoint (e.g., http://localhost:11434 for Ollama)

    # Telegram
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

    # LLM - model string determines the provider
    # Examples: "claude-sonnet-4-20250514", "gpt-4o", "gemini/gemini-2.5-flash",
    #           "groq/llama-3.3-70b-versatile", "ollama/llama3.1",
    #           "openrouter/anthropic/claude-sonnet-4"
    model: str = "claude-sonnet-4-20250514"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "spark.db"

    @property
    def chromadb_path(self) -> Path:
        return self.data_dir / "chromadb"

    @property
    def api_key(self) -> str:
        """Resolve the API key for the configured model.

        Priority: provider-specific key > generic llm_api_key > anthropic_api_key (legacy).
        """
        model_lower = self.model.lower()

        if model_lower.startswith("groq/") and self.groq_api_key:
            return self.groq_api_key
        if model_lower.startswith("gemini/") and self.gemini_api_key:
            return self.gemini_api_key
        if model_lower.startswith("openrouter/") and self.openrouter_api_key:
            return self.openrouter_api_key
        if model_lower.startswith(("gpt-", "o1-", "o3-")) and self.openai_api_key:
            return self.openai_api_key
        if "claude" in model_lower and self.anthropic_api_key:
            return self.anthropic_api_key

        # Fallbacks
        return self.llm_api_key or self.anthropic_api_key

    def setup_llm_env(self) -> None:
        """Set environment variables so litellm can find API keys."""
        import os

        key_map = {
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "OPENAI_API_KEY": self.openai_api_key,
            "GEMINI_API_KEY": self.gemini_api_key,
            "GROQ_API_KEY": self.groq_api_key,
            "OPENROUTER_API_KEY": self.openrouter_api_key,
        }
        for env_var, value in key_map.items():
            if value and not os.environ.get(env_var):
                os.environ[env_var] = value

    def ensure_dirs(self) -> None:
        """Create data directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> SparkSettings:
    """Load settings from environment / .env file."""
    return SparkSettings()
