"""Deterministic backtest of the stall rule on real git history.

Pure computation plus one `git log` call: no DB, network or LLM. The replay
copies the production rule exactly: threshold = round(avg_gap, 1) * multiplier,
and a stall fires when hours since the last commit is strictly greater.
"""

from __future__ import annotations

import statistics
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spark.core.rhythm import commit_gap_stats

RESUMED_24H = "resumed_24h"
RESUMED_7D = "resumed_7d"
RESUMED_14D = "resumed_14d"
REAL_STALL = "real_stall"
CENSORED = "censored"
LABELS = (RESUMED_24H, RESUMED_7D, RESUMED_14D, REAL_STALL, CENSORED)

_H = 3600.0


@dataclass
class Alert:
    last_commit: datetime
    alert_at: datetime
    hours_to_alert: float
    label: str


@dataclass
class RepoResult:
    name: str
    commits: int
    active_weeks: int
    alerts: list[Alert] = field(default_factory=list)
    missed: int = 0


def read_commit_times(path: str | Path, all_branches: bool = False) -> list[datetime]:
    """Sorted, UTC-aware commit timestamps from `git log`."""
    cmd = ["git", "-C", str(path), "log", "--format=%ct"]
    if all_branches:
        cmd.append("--all")
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return sorted(
        datetime.fromtimestamp(int(line), tz=timezone.utc)
        for line in out.split() if line.strip()
    )


def _hours(delta) -> float:
    return delta.total_seconds() / _H


def replay(
    timestamps: list[datetime], multiplier: float, end: datetime
) -> tuple[list[Alert], int]:
    """Replay the stall rule over every silence. Returns (alerts, missed)."""
    ts = sorted(timestamps)
    if not ts:
        return [], 0
    end = max(end, ts[-1])
    alerts: list[Alert] = []
    missed = 0
    for i, p in enumerate(ts):
        nxt = ts[i + 1] if i + 1 < len(ts) else None
        silence_end = nxt if nxt is not None else end
        base = round(commit_gap_stats([t for t in ts if t <= p])[0], 1)
        thr = base * multiplier
        silence_h = _hours(silence_end - p)
        if silence_h > thr:
            a = p + timedelta(hours=thr)
            if nxt is not None:
                r = _hours(nxt - a)
                if r <= 24:
                    label = RESUMED_24H
                elif r <= 168:
                    label = RESUMED_7D
                elif r < 336:
                    label = RESUMED_14D
                else:
                    label = REAL_STALL
            else:
                label = REAL_STALL if _hours(end - a) >= 336 else CENSORED
            alerts.append(Alert(p, a, thr, label))
        elif silence_h >= 336:
            missed += 1
    return alerts, missed


def _active_weeks(timestamps: list[datetime]) -> int:
    weeks = set()
    for t in timestamps:
        iso = t.astimezone(timezone.utc).isocalendar()
        weeks.add((iso[0], iso[1]))
    return len(weeks)


def analyze_repo(
    name: str, timestamps: list[datetime], multiplier: float, end: datetime
) -> RepoResult:
    alerts, missed = replay(timestamps, multiplier, end)
    return RepoResult(name, len(timestamps), _active_weeks(timestamps), alerts, missed)


def summarize(results: list[RepoResult]) -> dict:
    """Aggregate one or many repo results (pooled = summed counts, pooled median)."""
    alerts = [a for r in results for a in r.alerts]
    counts = {label: sum(1 for a in alerts if a.label == label) for label in LABELS}
    resolved = len(alerts) - counts[CENSORED]
    weeks = sum(r.active_weeks for r in results)

    def share(k: int) -> float | None:
        return k / resolved if resolved else None

    return {
        "commits": sum(r.commits for r in results),
        "active_weeks": weeks,
        "alerts": len(alerts),
        "alerts_per_active_week": len(alerts) / weeks if weeks else None,
        "counts": counts,
        "resolved": resolved,
        "share_24h": share(counts[RESUMED_24H]),
        "share_7d": share(counts[RESUMED_24H] + counts[RESUMED_7D]),
        "real_stall_precision": share(counts[REAL_STALL]),
        "missed": sum(r.missed for r in results),
        "median_hours_to_alert": (
            statistics.median(a.hours_to_alert for a in alerts) if alerts else None
        ),
    }


def _mkey(m: float) -> str:
    return f"{m:g}"


def run_backtest(
    paths: list[str],
    multipliers: list[float],
    all_branches: bool,
    as_of: datetime,
) -> dict:
    """Per repo and pooled summaries for each multiplier (aggregates only)."""
    history = [
        (Path(p).resolve().name, read_commit_times(p, all_branches)) for p in paths
    ]
    report: dict = {
        "as_of": as_of.date().isoformat(),
        "all_branches": all_branches,
        "multipliers": [_mkey(m) for m in multipliers],
        "pooled": {},
        "repos": {},
    }
    for m in multipliers:
        results = [analyze_repo(n, ts, m, as_of) for n, ts in history]
        report["pooled"][_mkey(m)] = summarize(results)
        report["repos"][_mkey(m)] = [
            {"name": r.name, **summarize([r])} for r in results
        ]
    return report


def _pct(k: int, n: int, share: float | None) -> str:
    return "n/a" if share is None else f"{share * 100:.0f}% ({k}/{n})"


def _f(v: float | None, nd: int) -> str:
    return "n/a" if v is None else f"{v:.{nd}f}"


_HEADER = (
    "| {first} | Commits | Active wks | Alerts | Alerts/active wk | resumed_24h | "
    "resumed_7d | resumed_14d | real_stall | censored | Resumed within 24h | "
    "Resumed within 7d | Real-stall precision | Missed | Median h to alert |"
)


def _row(first: str, s: dict) -> str:
    c = s["counts"]
    n = s["resolved"]
    return (
        f"| {first} | {s['commits']} | {s['active_weeks']} | {s['alerts']} | "
        f"{_f(s['alerts_per_active_week'], 2)} | {c[RESUMED_24H]} | {c[RESUMED_7D]} | "
        f"{c[RESUMED_14D]} | {c[REAL_STALL]} | {c[CENSORED]} | "
        f"{_pct(c[RESUMED_24H], n, s['share_24h'])} | "
        f"{_pct(c[RESUMED_24H] + c[RESUMED_7D], n, s['share_7d'])} | "
        f"{_pct(c[REAL_STALL], n, s['real_stall_precision'])} | {s['missed']} | "
        f"{_f(s['median_hours_to_alert'], 1)} |"
    )


def _table(first: str, rows: list[tuple[str, dict]]) -> list[str]:
    head = _HEADER.format(first=first)
    sep = "|" + "|".join(["---"] * (head.count("|") - 1)) + "|"
    return [head, sep, *(_row(label, s) for label, s in rows), ""]


def render_markdown(report: dict, command: str) -> str:
    branches = "all branches (--all)" if report["all_branches"] else "default checkout only"
    lines = [
        "# Stall-alarm backtest",
        "",
        f"- As-of date: {report['as_of']} (UTC midnight)",
        f"- Branches: {branches}",
        f"- Reproduce: `{command}`",
        "",
        "Shares use resolved (non-censored) alerts as the denominator, shown as k/n.",
        "",
        "## Pooled",
        "",
    ]
    lines += _table(
        "Setting",
        [(f"Pooled x{m}", report["pooled"][m]) for m in report["multipliers"]],
    )
    for m in report["multipliers"]:
        lines += [f"## Per repo, multiplier x{m}", ""]
        lines += _table("Repo", [(r["name"], r) for r in report["repos"][m]])
    return "\n".join(lines)
