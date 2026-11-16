"""CLI smoke tests, `spark doctor`, and dry-run delivery."""

import importlib
import pkgutil

import pytest
from typer.testing import CliRunner

import spark
from spark.cli import app
from spark.delivery.dry_run import DryRunAdapter

runner = CliRunner()

ENV_KEYS = ("SPARK_MODEL", "SPARK_EFFORT", "SPARK_THINKING", "SPARK_LLM_BACKEND",
            "SPARK_DRY_RUN", "SPARK_ANTHROPIC_API_KEY", "SPARK_TELEGRAM_BOT_TOKEN",
            "SPARK_TELEGRAM_CHAT_ID")


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no stray .env
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SPARK_DATA_DIR", str(tmp_path / "data"))
    return monkeypatch


def _full_config(mp):
    mp.setenv("SPARK_ANTHROPIC_API_KEY", "fake-key")
    mp.setenv("SPARK_TELEGRAM_BOT_TOKEN", "fake-token")
    mp.setenv("SPARK_TELEGRAM_CHAT_ID", "1")


def test_import_every_module():
    for mod in pkgutil.walk_packages(spark.__path__, "spark."):
        if mod.name == "spark.__main__":  # runs the CLI on import
            continue
        importlib.import_module(mod.name)


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "doctor" in result.output


def test_doctor_passes_offline(clean_env):
    _full_config(clean_env)
    from spark.core import llm

    clean_env.setattr(llm, "make_client", lambda k: pytest.fail("network used"))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "claude-sonnet-5-5" in result.output


def test_doctor_fails_on_retired_model(clean_env):
    _full_config(clean_env)
    clean_env.setenv("SPARK_MODEL", "claude-sonnet-4-20250514")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "retired" in result.output


def test_doctor_fails_without_key_or_telegram(clean_env):
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "API key" in result.output and "Telegram" in result.output


def test_doctor_live_reports_model_stop_reason_latency(clean_env):
    _full_config(clean_env)
    from spark.core import llm
    from tests.helpers import FakeClient, response, text_block

    clean_env.setattr(llm, "make_client", lambda k: FakeClient(response([text_block("ok")])))
    result = runner.invoke(app, ["doctor", "--live"])
    assert result.exit_code == 0, result.output
    assert "stop_reason=end_turn" in result.output and "latency=" in result.output


def test_doctor_live_failure_exits_nonzero(clean_env):
    _full_config(clean_env)
    from spark.core import llm
    from tests.helpers import FakeClient, response

    clean_env.setattr(llm, "make_client", lambda k: FakeClient(response([], "refusal")))
    result = runner.invoke(app, ["doctor", "--live"])
    assert result.exit_code != 0
    assert "Live call failed" in result.output


async def test_dry_run_writes_instead_of_sending(tmp_path, capsys, monkeypatch):
    import telegram

    monkeypatch.setattr(
        telegram.Bot, "send_message", lambda *a, **k: pytest.fail("Telegram used")
    )
    path = tmp_path / "data" / "dry_run_messages.log"
    adapter = DryRunAdapter(path)
    assert await adapter.send("hello co-founder") is True
    assert "hello co-founder" in capsys.readouterr().out
    assert "hello co-founder" in path.read_text()
