# Spark

Your AI co-founder. Built for solo-preneurs and developers who thrive on collaborative energy.

Spark bridges the gap between passive AI and active partnership. It monitors your projects, builds a living knowledge base, makes connections across your work, and reaches out via messaging platforms like a motivated co-founder who's been thinking about your stuff.

**This is not a reminder app.** Spark brings ideas, not notifications.

## How It Works

1. **Point Spark at your projects folder** - it monitors git activity and file changes
2. **Drop knowledge into your knowledge folder** - articles, notes, bookmarks, ideas
3. **Spark learns your rhythm** - commit frequency, active hours, day-of-week patterns
4. **When things stall, Spark reaches out** - via Telegram with a specific idea, a connection it noticed, or a small contribution ready to go

A reminder app says: *"You haven't committed in 2 days."*

Spark says: *"I was looking at your auth module and that article you bookmarked about httpOnly cookies. What if you ditched the refresh token dance entirely? I stubbed out what that might look like."*

## Quick Start

```bash
# Install
pip install -e .

# Configure (copy and edit)
cp .env.example .env

# Register a project
cd ~/projects/my-app
spark init --desc "SaaS dashboard" --goal "Finish the billing integration"

# Check status
spark status

# Start the agent
spark run
```

## Configuration

Set these in your `.env` file:

| Variable | Required | Description |
|---|---|---|
| `SPARK_ANTHROPIC_API_KEY` | Yes | Claude API key |
| `SPARK_TELEGRAM_BOT_TOKEN` | Yes | Telegram bot token from @BotFather |
| `SPARK_TELEGRAM_CHAT_ID` | Yes | Your Telegram chat ID |
| `SPARK_PROJECTS_DIR` | No | Projects folder (default: `~/projects`) |
| `SPARK_KNOWLEDGE_DIR` | No | Knowledge dump folder (default: `~/knowledge`) |
| `SPARK_TIMEZONE` | No | Your timezone (default: `UTC`) |
| `SPARK_AGENCY_LEVEL` | No | `suggest`, `light`, or `full` (default: `suggest`) |
| `SPARK_MAX_DAILY_NUDGES` | No | Max messages per day (default: `3`) |

## Agency Levels

- **suggest** - Ideas, encouragement, specific next steps. You stay in the driver's seat.
- **light** - Can draft outlines, stub functions, write TODOs, research blockers.
- **full** - Can open PRs, write code, create issues. Acts like a real async co-founder.

## CLI Commands

| Command | Description |
|---|---|
| `spark init` | Register a project for tracking |
| `spark setup` | Show current configuration |
| `spark status` | Show all tracked projects |
| `spark run` | Start the Spark daemon |
| `spark pause [project]` | Pause nudges |
| `spark resume [project]` | Resume nudges |
| `spark goal <project> <text>` | Update a project's current goal |

## Telegram Commands

Once running, you can also interact via Telegram:

- `/status` - Project overview
- `/projects` - List tracked projects
- `/pause` - Silence Spark
- `/resume` - Resume nudges
- Or just reply to any message to continue the conversation

## Architecture

```
Signal Ingestion  -->  Knowledge Engine  -->  Delivery Layer
(git, files,           (index, embeddings,    (Telegram, Signal,
 knowledge folder)      connections)           Discord, WhatsApp)
                              |
                        Spark Core
                        (stall detection,
                         context analysis,
                         message composition,
                         memory)
```

## License

AGPL-3.0 - see [LICENSE](LICENSE)
