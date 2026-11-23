"""Backtest replay, commit_gap_stats, and the `spark backtest` CLI (all offline)."""

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

from typer.testing import CliRunner

from spark.cli import app
from spark.core.backtest import (
    CENSORED,
    REAL_STALL,
    RESUMED_7D,
    RESUMED_14D,
    RESUMED_24H,
    Alert,
    RepoResult,
    replay,
    summarize,
)
from spark.core.rhythm import commit_gap_stats, compute_rhythm_profile
from spark.db.connection import get_session, init_db
from spark.db.models import ActivityEvent, EventType, Project

runner = CliRunner()
# Captured from compute_rhythm_profile BEFORE commit_gap_stats was extracted.
EXPECTED_PROFILE = {
    "avg_commit_gap_hours": 14.3,
    "median_commit_gap_hours": 9.2,
    "active_days_per_week": 1.4,
    "typical_hours": [0, 2, 8],
    "day_of_week_activity": {5: 1, 6: 4, 1: 1, 2: 4, 4: 1},
    "total_commits": 11,
    "last_commit_at": "2026-03-01T12:00:00",
}


def test_rhythm_profile_unchanged(tmp_path):
    init_db(tmp_path / "t.db")
    latest = datetime(2026, 3, 1, 12, 0, 0)
    offsets_h = [
        -960, -840,  # more than 30 days before the latest commit: excluded
        -700, -500,  # 200h gap (ignored, >= 168h)
        -300, -100, -99.5, -99.2, -90, -60, -10, -9.6, 0,
    ]
    with get_session() as s:
        p = Project(name="r", local_path=str(tmp_path))
        s.add(p)
        s.flush()
        pid = p.id
        for h in offsets_h:
            s.add(ActivityEvent(project_id=pid, event_type=EventType.COMMIT.value,
                                event_data={}, occurred_at=latest + timedelta(hours=h)))
    assert compute_rhythm_profile(pid) == EXPECTED_PROFILE


T0 = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _ts(*gaps_h):
    """Commit times starting at T0 separated by the given gaps (hours)."""
    out = [T0]
    for g in gaps_h:
        out.append(out[-1] + timedelta(hours=g))
    return out


def _end(ts, extra_h=0):
    return ts[-1] + timedelta(hours=extra_h)


# Baseline of 10 commits 10h apart is 10h; mult 2 -> threshold 20h.
def _steady(n=10):
    return [10] * (n - 1)


def test_label_resumed_24h():
    ts = _ts(*_steady(), 30)  # alert at +20h, return at +30h (r=10h)
    alerts, missed = replay(ts, 2, _end(ts))
    assert [a.label for a in alerts] == [RESUMED_24H] and missed == 0


def test_label_resumed_7d():
    ts = _ts(*_steady(), 100)  # r=80h
    assert [a.label for a in replay(ts, 2, _end(ts))[0]] == [RESUMED_7D]


def test_label_resumed_14d():
    ts = _ts(*_steady(), 300)  # r=280h, 7-14d
    alerts, _ = replay(ts, 2, _end(ts))
    assert [a.label for a in alerts] == [RESUMED_14D]


def test_label_real_stall_from_next_commit():
    ts = _ts(*_steady(), 400)  # r=380h >= 336h
    alerts, _ = replay(ts, 2, _end(ts))
    assert [a.label for a in alerts] == [REAL_STALL]


def test_label_real_stall_from_trailing_silence():
    ts = _ts(*_steady())
    alerts, _ = replay(ts, 2, _end(ts, 20 + 336))  # end - alert == 336h exactly
    assert [a.label for a in alerts] == [REAL_STALL]


def test_label_censored_trailing_silence():
    ts = _ts(*_steady())
    alerts, _ = replay(ts, 2, _end(ts, 20 + 335))
    assert [a.label for a in alerts] == [CENSORED]
    assert alerts[0].hours_to_alert == 20.0


def test_one_alert_per_gap_on_very_long_gap():
    ts = _ts(*_steady(), 5000)
    alerts, _ = replay(ts, 2, _end(ts))
    assert len(alerts) == 1


def test_no_alert_when_silence_equals_threshold():
    ts = _ts(*_steady(), 20)  # silence == threshold exactly: strict ">" => none
    alerts, _ = replay(ts, 2, _end(ts))
    assert alerts == []


def test_missed_long_gap_without_alert():
    ts = _ts(100, 100, 400)
    alerts8, missed8 = replay(ts, 8, _end(ts))
    assert missed8 == 1 and alerts8 == []
    alerts2, missed2 = replay(ts, 2, _end(ts))
    assert missed2 == 0
    assert [a.label for a in alerts2 if a.last_commit == ts[2]] == [RESUMED_14D]


def test_first_gap_uses_24h_default_baseline():
    ts = _ts(30)  # one gap only: baseline before first commit is 24h default
    alerts, _ = replay(ts, 1, _end(ts))
    assert len(alerts) == 1 and alerts[0].hours_to_alert == 24.0


def test_commit_gap_stats_window_filter_and_default():
    assert commit_gap_stats([]) == (24.0, 24.0)
    assert commit_gap_stats([T0]) == (24.0, 24.0)
    assert commit_gap_stats(_ts(200)) == (24.0, 24.0)  # only gap >= 168h
    ts = _ts(1000, 10, 20)  # first commit is >30d before the last: excluded
    assert commit_gap_stats(list(reversed(ts))) == (15.0, 20.0)
    assert commit_gap_stats(ts, lookback_days=60)[0] == 15.0


def _res(labels, hours=10.0, name="r"):
    alerts = [Alert(T0, T0, hours, lab) for lab in labels]
    return RepoResult(name, 5, 2, alerts, 0)


def test_summarize_shares_and_none_handling():
    s = summarize([_res([RESUMED_24H, RESUMED_7D, REAL_STALL, CENSORED])])
    assert s["resolved"] == 3
    assert s["share_24h"] == 1 / 3 and s["share_7d"] == 2 / 3
    assert s["real_stall_precision"] == 1 / 3
    empty = summarize([_res([CENSORED]), _res([], name="e")])
    assert empty["real_stall_precision"] is None and empty["share_7d"] is None
    none = summarize([_res([])])
    assert none["median_hours_to_alert"] is None
    pooled = summarize([_res([RESUMED_24H], 4.0), _res([REAL_STALL], 8.0)])
    assert pooled["commits"] == 10 and pooled["median_hours_to_alert"] == 6.0


def _git(repo, *args, date="2020-01-01T00:00:00+0000"):
    e = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=e)


def _make_repo(path, days):
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "a@b.c")
    _git(path, "config", "user.name", "T")
    for i, d in enumerate(days):
        (path / f"f{i}").write_text(str(i))
        _git(path, "add", ".")
        day = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=d)
        _git(path, "commit", "-q", "-m", f"c{i}", date=day.strftime("%Y-%m-%dT%H:%M:%S+0000"))


def test_cli_backtest_multiplier_tokens_and_outputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = tmp_path / "demo"
    _make_repo(repo, [0, 1, 2, 3, 20, 21, 60])
    md, js = tmp_path / "out.md", tmp_path / "out.json"
    r = runner.invoke(app, ["backtest", str(repo), "--multiplier", "2", "4", "8",
                            "--as-of", "2020-06-01", "--out", str(md), "--json", str(js)])
    assert r.exit_code == 0, r.output
    data = json.loads(js.read_text())
    assert data["multipliers"] == ["2", "4", "8"]
    assert set(data["pooled"]) == {"2", "4", "8"}
    assert len(data["repos"]["2"]) == 1 and data["repos"]["2"][0]["name"] == "demo"
    assert "Pooled" in md.read_text()


def test_cli_backtest_all_branches_smoke(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = tmp_path / "demo"
    _make_repo(repo, [0, 1, 2])
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "x").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "side", date="2020-01-10T00:00:00+0000")
    _git(repo, "checkout", "-q", "-")
    js = tmp_path / "o.json"
    r = runner.invoke(app, ["backtest", str(repo), "--all-branches", "--as-of", "2020-06-01",
                            "--json", str(js)])
    assert r.exit_code == 0, r.output
    assert json.loads(js.read_text())["pooled"]["2"]["commits"] == 4


def test_cli_backtest_missing_path_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["backtest", str(tmp_path / "nope")])
    assert r.exit_code == 1
