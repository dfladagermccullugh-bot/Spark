"""Settings defaults and the single-source-of-truth model constant."""

from pathlib import Path

import pytest

from spark.config import DEFAULT_MODEL, RETIRED_MODELS, SparkSettings

RETIRED = "claude-sonnet-4-20250514"


def _settings(monkeypatch, tmp_path, **env):
    monkeypatch.chdir(tmp_path)
    for k in ("SPARK_MODEL", "SPARK_EFFORT", "SPARK_THINKING", "SPARK_LLM_BACKEND",
              "SPARK_DRY_RUN"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return SparkSettings(_env_file=None)


def test_defaults(monkeypatch, tmp_path):
    s = _settings(monkeypatch, tmp_path)
    assert DEFAULT_MODEL == "claude-sonnet-5-5"
    assert s.model == DEFAULT_MODEL
    assert s.effort == "medium"
    assert s.thinking == "between_tools"
    assert s.llm_backend == "anthropic"
    assert s.dry_run is False


def test_env_overrides(monkeypatch, tmp_path):
    s = _settings(
        monkeypatch, tmp_path,
        SPARK_MODEL="claude-opus-5-5", SPARK_EFFORT="high", SPARK_THINKING="adaptive",
        SPARK_LLM_BACKEND="claude-cli", SPARK_DRY_RUN="true",
    )
    assert (s.model, s.effort, s.thinking) == ("claude-opus-5-5", "high", "adaptive")
    assert s.llm_backend == "claude-cli"
    assert s.dry_run is True


def test_invalid_effort_rejected(monkeypatch, tmp_path):
    with pytest.raises(Exception):
        _settings(monkeypatch, tmp_path, SPARK_EFFORT="extreme")


def test_llm_configured(monkeypatch, tmp_path):
    s = _settings(monkeypatch, tmp_path, SPARK_ANTHROPIC_API_KEY="")
    assert not s.llm_configured
    assert _settings(monkeypatch, tmp_path, SPARK_LLM_BACKEND="claude-cli").llm_configured


def test_retired_model_string_only_in_retired_list():
    assert RETIRED in RETIRED_MODELS
    offenders = [
        str(p) for p in Path("spark").rglob("*.py")
        if RETIRED in p.read_text() and p.name != "config.py"
    ]
    assert offenders == []
    config_hits = [
        line for line in Path("spark/config.py").read_text().splitlines() if RETIRED in line
    ]
    assert len(config_hits) == 1  # the RETIRED_MODELS entry only
