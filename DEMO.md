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
