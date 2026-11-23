# Spark demo: one real pass on a real, stalled portfolio

## The problem
Solo builders and indie hackers juggle many side projects and lose momentum *silently*. Nobody
notices when a project goes quiet, least of all you. Reminder apps nag on a fixed schedule with
no idea what the project is. Spark watches your git history, learns **your own** rhythm per
project, notices when a project goes quiet relative to that rhythm, and sends **one specific,
context-aware next step** drawn from the repo (README, recent commits, file tree).

## Who has it
Anyone with more side projects than weekly hours: indie hackers, solo founders, open-source
maintainers, hobbyists with a graveyard of half-built repos.

## The scenario
Spark is pointed at the owner's real GitHub portfolio (`dfladagermccullugh-bot`:
Kaban-Plus-Ultra, ThoughStream, MCP-Bridge-Dashboard). Each was last touched 6-7 months ago, so
they are genuine stalls rather than staged ones.

Spark itself was a victim of the same failure mode: it ran for ~5 months against a retired
model and failed *silently*, so no nudges went out and nobody noticed. The fix on this branch is
**loud failures** (errors logged, owner alerted once, non-zero CLI exits) plus `spark doctor
--live` to verify the model before you trust the agent. The demo exercises both.

## Run it
```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # once
bash scripts/demo.sh                                            # claude-cli backend (needs `claude` logged in)
# or with an API key:
SPARK_LLM_BACKEND=anthropic SPARK_ANTHROPIC_API_KEY=sk-... bash scripts/demo.sh
```
The script uses an isolated data dir (`/tmp/spark-demo`, override with `SPARK_DEMO_DIR`), clones
the repos if absent, forces `SPARK_DRY_RUN=true` and blanks the Telegram credentials, so nothing
can be sent. Steps: `spark doctor --live`, `spark init` x3, `spark status`,
`spark check --dry-run --force`. `check` is one pass of the daemon loop (collect, baselines,
stalls, nudge, deliver); `--force` skips quiet hours and nudge rate limits so it runs any time.

## Real output
Full capture: [`docs/demo-output.txt`](docs/demo-output.txt).

```
=== spark status ===
│ Kaban-Plus-Ultra     │ active │ 183d ago │ ~2h │ 0 │
│ ThoughStream         │ active │ 200d ago │ ~4h │ 0 │
│ MCP-Bridge-Dashboard │ active │ 220d ago │ ~1h │ 0 │

=== spark check --dry-run --force ===
│ MCP-Bridge-Dashboard │ 5278 │ 1.4 │ 1.00 │     (project, hours since activity,
│ Kaban-Plus-Ultra     │ 4402 │ 1.9 │ 1.00 │      baseline gap in hours, confidence)
│ ThoughStream         │ 4807 │ 3.8 │ 1.00 │
```
- **status**: rhythm (`~2h`) is the typical gap between commits *while the project was active*,
  learned from real history; "183d ago" is how long it has been quiet.
- **check**: a project is stalled when silence exceeds `baseline gap x multiplier` (default 2x).
  Here silence is thousands of hours against a 1-4h rhythm, so confidence is capped at 1.00. The
  top stall gets a nudge, written by Claude from that repo's own files and git log, then
  delivered through the dry-run adapter (printed and appended to `dry_run_messages.log`).

The nudge Claude (`claude-sonnet-5-5`, via the `claude-cli` backend) wrote for the top stall,
captured Nov 15, 2026 and delivered only to the dry-run log:

> Been thinking about that `--log-driver none` fix. It solves the stdio timeout, but it also
> means you're blind when a server crashes on startup. What if buildEngine ran a quick smoke test
> right after the build: spin up the container, send a JSON-RPC `initialize`, and only write the
> config entry if it answers?
>
> That gets you to real one-click, because "installed" would mean "verified working" instead of
> "image built." And if the handshake fails, you can show the stderr in BuildModal.tsx instead of
> leaving the user to find out in Claude Desktop.

Why it's a good demo: every detail is grounded in the repo. `--log-driver none` is the real last
functional commit (`a38a16c Fix MCP server timeout: add --log-driver none...`), and `buildEngine.ts`
and `BuildModal.tsx` are real files. The suggestion ties straight back to the project's stated goal
("one-click MCP server install working end to end"). A reminder app would have said "You haven't
committed in 220 days."

## Mocked vs real
| Part | Status |
|---|---|
| Git history, activity events, rhythm baselines, stall detection | **Real** (cloned repos) |
| Claude call (nudge generation, `doctor --live`) | **Real** (`claude-sonnet-5-5`; `doctor --live` round-trip 1.6s) |
| Delivery | **Dry-run**: printed and logged, never sent to Telegram |
| Project descriptions/goals | Written by hand in the script |
| Tests | Offline, LLM mocked (`pytest`) |

## Bugs the demo surfaced and fixed
- Rhythm baseline fell back to a meaningless 24h default for any project stalled > 30 days
  (the lookback window is now anchored to the last commit).
- Nudge generation crashed with `DetachedInstanceError` reading the project path after its DB
  session closed.
- `claude` CLI failures printed truncated JSON; they now show the actual message.

## Backtest: is Spark's stall alarm trustworthy?

`spark backtest` replays the production stall rule (`round(avg_gap, 1) * multiplier`, strict `>`)
over real git history: for every silence between commits it recomputes the baseline as it was at
that moment, fires an alert once the threshold is crossed, and labels what happened next. No DB,
network or LLM is involved, so the numbers are reproducible. As-of date: 2026-11-23 (UTC).

Commands (full per-repo tables are in `docs/backtest-2026-11.md` and
`docs/backtest-2026-11-all-branches.md`):

```
spark backtest /workspace/spark-backtest-repos/* --multiplier 2 4 8 --as-of 2026-11-23 --out docs/backtest-2026-11.md
spark backtest /workspace/spark-backtest-repos/* --multiplier 2 4 8 --as-of 2026-11-23 --all-branches --out docs/backtest-2026-11-all-branches.md
```

Default checkout:

| Setting | Commits | Active wks | Alerts | Alerts/active wk | resumed_24h | resumed_7d | resumed_14d | real_stall | censored | Resumed within 24h | Resumed within 7d | Real-stall precision | Missed | Median h to alert |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Pooled x2 | 396 | 18 | 61 | 3.39 | 44 | 0 | 1 | 12 | 4 | 77% (44/57) | 77% (44/57) | 21% (12/57) | 0 | 0.6 |
| Pooled x4 | 396 | 18 | 45 | 2.50 | 28 | 0 | 1 | 12 | 4 | 68% (28/41) | 68% (28/41) | 29% (12/41) | 0 | 1.2 |
| Pooled x8 | 396 | 18 | 39 | 2.17 | 23 | 0 | 1 | 12 | 3 | 64% (23/36) | 64% (23/36) | 33% (12/36) | 0 | 2.4 |

All branches (`git log --all`):

| Setting | Commits | Active wks | Alerts | Alerts/active wk | resumed_24h | resumed_7d | resumed_14d | real_stall | censored | Resumed within 24h | Resumed within 7d | Real-stall precision | Missed | Median h to alert |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Pooled x2 | 441 | 18 | 71 | 3.94 | 54 | 0 | 1 | 12 | 4 | 81% (54/67) | 81% (54/67) | 18% (12/67) | 0 | 0.4 |
| Pooled x4 | 441 | 18 | 55 | 3.06 | 38 | 0 | 1 | 12 | 4 | 75% (38/51) | 75% (38/51) | 24% (12/51) | 0 | 1.2 |
| Pooled x8 | 441 | 18 | 47 | 2.61 | 30 | 0 | 1 | 12 | 4 | 70% (30/43) | 70% (30/43) | 28% (12/43) | 0 | 2.4 |

Labels (what the author did after the alert): `resumed_24h`, `resumed_7d` (24h to 7d),
`resumed_14d` (7 to 14d), `real_stall` (no commit for 14d+), `censored` (still inside the 14-day
window at the as-of date; excluded from every share). Shares are `k/n` over non-censored alerts.

### Honest reading

- Volume is high at the current default (x2): 61 alerts over 18 active weeks (3.39 per active
  week) on the default checkout, and only 21% (12/57) of resolved alerts were followed by a real
  stall. Most alerts (77%) are followed by a commit within 24h, i.e. a nudge that was not needed.
- Raising the multiplier removes false alarms without losing real stalls: the 12 real stalls
  are found at x2, x4 and x8, and nothing was missed (missed = 0). Alerts drop 61 to 45 to 39, and
  precision rises 21% to 29% to 33%. On this data x8 is the best-supported choice of the three,
  but even there two thirds of resolved alerts are not real stalls.
- The median alert threshold is only 0.6h to 2.4h, because commits come in bursts and the baseline
  gap is tiny. A "stall" alarm at that scale mostly measures a lunch break, which suggests the
  baseline (not only the multiplier) deserves a look. I did not change the default.
- `all-branches` adds commits (441 vs 396) and more alerts, but the same 12 real stalls.

### Caveats

- Small, uneven sample: 2 to 140 commits per repo, 11 repos, 18 active weeks pooled; one repo
  (Verity) has about a third of the commits.
- Default branches are often squash-merged, so the default-checkout history under-counts real
  working rhythm; `--all-branches` is the closer view but includes unmerged work.
- Results depend on the as-of date: trailing silences are judged up to 2026-11-23, and later
  runs would turn some `censored` alerts into `real_stall` or resumed ones.
- Commits only: the running daemon also resets the stall clock on file edits (the file watcher sets
  `last_activity_at`), so for someone running the watcher the backtest over-counts alerts.
- Edge case the data exposed: for very bursty repos `round(avg_gap, 1)` rounds to 0.0h, so the
  threshold is 0 and production would call any pause a stall (median 0.0h to alert for
  everyday_watcher, and Spark with `--all-branches`, in the per-repo tables). A minimum baseline
  is the obvious follow-up; not changed here.
- `resumed_14d` (return 7 to 14 days after the alert) is my addition to the original four
  labels, so every alert gets exactly one label.
