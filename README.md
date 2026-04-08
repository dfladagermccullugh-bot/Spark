# Spark

Your AI co-founder. Built for solo-preneurs and developers who thrive on collaborative energy.

Spark bridges the gap between passive AI and active partnership. It monitors your projects, builds a living knowledge base, makes connections across your work and interests, and reaches out via Telegram like a motivated co-founder who's been thinking about your stuff. It writes code, pushes branches, researches blockers, and gets smarter the more you interact with it.

**This is not a reminder app.** Spark brings ideas, contributions, and momentum. It learns what works for you and adapts.

## How It Works

1. **Point Spark at your projects folder** - it monitors git activity and file changes
2. **Feed it knowledge** - drop articles and notes into your knowledge folder, import browser bookmarks, YouTube favorites, or Twitter/X bookmarks
3. **Spark learns your rhythm** - commit frequency, active hours, day-of-week patterns
4. **When things stall, Spark reaches out** - via Telegram with a specific idea, a connection between your saved knowledge and your project, or a ready-to-submit code contribution
5. **Tell Spark to do things** - ask it to stub out an endpoint, research a blocker, or draft a test file, and it will create a branch with the work done
6. **Spark learns and adapts** - tracks which nudges lead to action, remembers your preferences, sends daily/weekly project digests, and enriches your knowledge base by fetching URL content

A reminder app says: *"You haven't committed in 2 days."*

Spark says: *"I was looking at your auth module and that article you bookmarked about httpOnly cookies. What if you ditched the refresh token dance entirely? I stubbed out what that might look like - branch is ready if you want to check it."*

## Quick Start

```bash
# Install
pip install -e .

# Configure (copy and edit)
cp .env.example .env

# Register a project
cd ~/projects/my-app
spark init --desc "SaaS dashboard" --goal "Finish the billing integration"

# Import your browser bookmarks
spark import-bookmarks ~/path/to/Bookmarks

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
| `SPARK_DAILY_DIGEST_ENABLED` | No | Enable daily project digest (default: `true`) |
| `SPARK_WEEKLY_DIGEST_ENABLED` | No | Enable weekly retrospective (default: `true`) |
| `SPARK_ENRICH_KNOWLEDGE` | No | Auto-fetch URL content for bookmarks (default: `true`) |
| `SPARK_LEARN_FROM_CONVERSATIONS` | No | Extract preferences from chats (default: `true`) |

## Agency Levels

Controls how much Spark can do on its own:

- **suggest** - Ideas, encouragement, specific next steps. You stay in the driver's seat.
- **light** - Can write code and research autonomously. Branch/push requires your approval ("go" / "skip").
- **full** - Fully autonomous. Writes code, creates branches, pushes changes. Acts like a real async co-founder.

## CLI Commands

### Project Management

| Command | Description |
|---|---|
| `spark init` | Register a project for tracking |
| `spark setup` | Show current configuration |
| `spark status` | Show all tracked projects |
| `spark run` | Start the Spark daemon |
| `spark pause [project]` | Pause nudges |
| `spark resume [project]` | Resume nudges |
| `spark goal <project> <text>` | Update a project's current goal |

### Knowledge Base

| Command | Description |
|---|---|
| `spark knowledge` | Show knowledge base stats |
| `spark import-bookmarks <file>` | Import Chrome or Firefox bookmarks |
| `spark import-youtube <file>` | Import YouTube likes/history (Google Takeout) |
| `spark import-twitter <file>` | Import Twitter/X bookmarks |
| `spark search-knowledge <query>` | Semantic search across your knowledge base |

### Actions

| Command | Description |
|---|---|
| `spark do <instruction>` | Ask Spark to write code on a project |
| `spark research <question>` | Research a topic using knowledge base + project context |

### Intelligence

| Command | Description |
|---|---|
| `spark digest` | Get a project digest right now |
| `spark memories` | Show what Spark has learned about you |
| `spark effectiveness` | Show nudge effectiveness statistics |
| `spark enrich` | Fetch and summarize URL content for knowledge items |

## Telegram Commands

Once running, interact with Spark via Telegram:

| Command | Description |
|---|---|
| `/status` | Project overview |
| `/projects` | List tracked projects |
| `/knowledge` | Knowledge base stats |
| `/do <task>` | Ask Spark to write code |
| `/research <question>` | Research a topic |
| `/pending` | Show proposals awaiting approval |
| `/digest` | Get a project digest now |
| `/memories` | What Spark has learned about you |
| `/effectiveness` | Nudge effectiveness stats |
| `/pause` | Silence Spark |
| `/resume` | Resume nudges |
| `go` | Approve a pending proposal |
| `skip` | Reject a pending proposal |

Or just reply to any message to continue the conversation.

## Architecture

```
+---------------------+     +--------------------+     +-------------------+
| Signal Ingestion    |     | Knowledge Engine   |     | Delivery Layer    |
|                     |     |                    |     |                   |
| - Git activity      |---->| - ChromaDB vectors |---->| - Telegram bot    |
| - File watcher      |     | - Semantic search  |     | - Daily digest    |
| - Knowledge folder  |     | - Cross-project    |     | - Weekly retro    |
| - Browser bookmarks |     |   connections      |     +-------------------+
| - YouTube / Twitter |     | - URL enrichment   |            ^
+---------------------+     +--------------------+            |
                                    |                          |
                             +--------------------+           |
                             | Spark Core         |-----------+
                             |                    |
                             | - Rhythm profiler  |     +-------------------+
                             | - Stall detector   |     | Action Engine     |
                             | - Context engine   |---->|                   |
                             | - Nudge generator  |     | - Code generation |
                             | - Co-founder       |     |   (Claude tools)  |
                             |   persona          |     | - Git branch/push |
                             +--------------------+     | - Research        |
                                    |                   | - Authorization   |
                             +--------------------+     |   (persistent)    |
                             | Learning Brain     |     +-------------------+
                             |                    |
                             | - Memory system    |
                             | - Feedback loop    |
                             | - Effectiveness    |
                             |   tracking         |
                             +--------------------+
                                    |
                                    v
                             +--------------------+
                             | Data Store         |
                             |                    |
                             | - SQLite (projects,|
                             |   events, messages,|
                             |   knowledge, tasks,|
                             |   memories,        |
                             |   feedback)        |
                             | - ChromaDB         |
                             |   (embeddings)     |
                             +--------------------+
```

## Tech Stack

| Component | Choice |
|---|---|
| Language | Python 3.11+ |
| LLM | Claude API (Anthropic SDK) |
| Database | SQLite + SQLAlchemy |
| Vector Store | ChromaDB (local, no server needed) |
| File Watching | watchdog |
| Git Analysis | gitpython |
| Scheduling | APScheduler |
| CLI | Typer + Rich |
| Messaging | python-telegram-bot |

## License

AGPL-3.0 - see [LICENSE](LICENSE)
