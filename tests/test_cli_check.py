"""`spark check`: one offline pass of the daemon loop with a mocked LLM."""

import subprocess

import pytest
from typer.testing import CliRunner

from spark.cli import app
from spark.core import llm
from tests.helpers import FakeClient, response, text_block

runner = CliRunner()
OLD = "2020-01-01T12:00:00"


def _git(repo, *args, **env):
    import os
    e = {**os.environ, "GIT_AUTHOR_DATE": OLD, "GIT_COMMITTER_DATE": OLD, **env}
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=e)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    projects = tmp_path / "projects"
    repo = projects / "stale"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "a@b.c")
    _git(repo, "config", "user.name", "T")
    for i in range(3):
        (repo / f"f{i}.txt").write_text(str(i))
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"commit {i}")
    for k, v in {
        "SPARK_DATA_DIR": tmp_path / "data", "SPARK_PROJECTS_DIR": projects,
        "SPARK_KNOWLEDGE_DIR": tmp_path / "k", "SPARK_ANTHROPIC_API_KEY": "fake",
        "SPARK_DRY_RUN": "true", "SPARK_LLM_BACKEND": "anthropic",
        "SPARK_QUIET_HOURS_START": "00:00", "SPARK_QUIET_HOURS_END": "23:59",
    }.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.delenv("SPARK_TELEGRAM_BOT_TOKEN", raising=False)
    r = runner.invoke(app, ["init", str(repo), "-d", "demo project", "-g", "ship it"])
    assert r.exit_code == 0, r.output
    return monkeypatch, tmp_path


def test_check_force_generates_and_dry_runs(setup):
    mp, tmp = setup
    client = FakeClient(response([text_block("Try finishing the parser tests today.")]))
    mp.setattr(llm, "make_client", lambda k: client)
    r = runner.invoke(app, ["check", "--dry-run", "--force"])
    assert r.exit_code == 0, r.output
    assert "stale" in r.output and "Detected stalls" in r.output
    assert "Try finishing the parser tests today." in r.output
    log = (tmp / "data" / "dry_run_messages.log").read_text()
    assert "parser tests" in log


def test_check_blocked_by_quiet_hours_without_force(setup):
    mp, _ = setup
    mp.setattr(llm, "make_client", lambda k: pytest.fail("LLM must not be called"))
    r = runner.invoke(app, ["check", "--dry-run"])
    assert r.exit_code == 0
    assert "No stalled projects" in r.output


def test_check_llm_failure_exits_nonzero(setup):
    mp, _ = setup
    mp.setattr(llm, "make_client", lambda k: FakeClient(RuntimeError("boom")))
    r = runner.invoke(app, ["check", "--dry-run", "--force"])
    assert r.exit_code == 1
    assert "Claude call failed" in r.output
