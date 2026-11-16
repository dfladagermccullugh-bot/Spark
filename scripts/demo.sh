#!/usr/bin/env bash
# End-to-end Spark demo on real repos. Never sends to Telegram (dry-run, tokens unset).
# Usage: scripts/demo.sh            (uses the claude CLI; or SPARK_LLM_BACKEND=anthropic + API key)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_ROOT="${SPARK_DEMO_DIR:-${TMPDIR:-/tmp}/spark-demo}"
PROJECTS="${SPARK_PROJECTS_DIR:-$DEMO_ROOT/projects}"
OWNER_URL="https://github.com/dfladagermccullugh-bot"

export SPARK_DATA_DIR="${SPARK_DATA_DIR:-$DEMO_ROOT/data}"
export SPARK_KNOWLEDGE_DIR="${SPARK_KNOWLEDGE_DIR:-$DEMO_ROOT/knowledge}"
export SPARK_PROJECTS_DIR="$PROJECTS"
export SPARK_DRY_RUN=true
export SPARK_LLM_BACKEND="${SPARK_LLM_BACKEND:-claude-cli}"
# Guarantee nothing can reach Telegram, even if the caller's env/.env has credentials.
export SPARK_TELEGRAM_BOT_TOKEN="" SPARK_TELEGRAM_CHAT_ID=""

# Prefer the repo venv if present.
if [[ -x "$REPO_ROOT/.venv/bin/spark" ]]; then SPARK="$REPO_ROOT/.venv/bin/spark"; else SPARK="spark"; fi

rm -rf "$SPARK_DATA_DIR"            # fresh DB each run
mkdir -p "$PROJECTS" "$SPARK_KNOWLEDGE_DIR"
cd "$DEMO_ROOT" 2>/dev/null || cd "$REPO_ROOT"   # avoid picking up a stray .env

for repo in Kaban-Plus-Ultra ThoughStream MCP-Bridge-Dashboard; do
  [[ -d "$PROJECTS/$repo/.git" ]] || git clone --quiet "$OWNER_URL/$repo.git" "$PROJECTS/$repo"
done

step() { printf '\n=== %s ===\n' "$*"; }

step "spark doctor --live (backend=$SPARK_LLM_BACKEND)"
"$SPARK" doctor --live

step "spark init (register projects)"
"$SPARK" init "$PROJECTS/Kaban-Plus-Ultra" --name Kaban-Plus-Ultra \
  -d "Kanban board with true 2D swimlanes (rows x columns), markdown cards; web, iOS and Android from one TypeScript codebase" \
  -g "Get a usable end-to-end board (create, move, persist cards) in front of real users"
"$SPARK" init "$PROJECTS/ThoughStream" --name ThoughStream \
  -d "Self-hosted shared idea board: one Go binary, SQLite, vanilla JS PWA, mobile-first" \
  -g "Ship the first deployable build and capture my own ideas with it daily"
"$SPARK" init "$PROJECTS/MCP-Bridge-Dashboard" --name MCP-Bridge-Dashboard \
  -d "Local dashboard that automates install, Docker build and config of MCP servers for Claude Desktop/Code on Windows" \
  -g "Get one-click MCP server install working end to end"

step "spark status"
"$SPARK" status

step "spark check --dry-run --force (one pass of the daemon loop)"
"$SPARK" check --dry-run --force

step "dry-run log (what would have gone to Telegram)"
tail -n 20 "$SPARK_DATA_DIR/dry_run_messages.log"
