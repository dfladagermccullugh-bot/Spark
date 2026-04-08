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

Already have Python 3.11+ and know your way around? Here's the 60-second version:

```bash
git clone https://github.com/dfladagermccullugh-bot/Spark.git
cd Spark
pip install -e .
cp .env.example .env          # then edit with your API keys (see below)
spark init ~/projects/my-app --desc "SaaS dashboard" --goal "Ship billing"
spark run
```

## Full Installation

### Prerequisites

- **Python 3.11+** (`python3 --version` to check)
- **Git** (for project activity tracking)
- **A Claude API key** from [console.anthropic.com](https://console.anthropic.com/)
- **A Telegram bot** (setup instructions below)

### Step 1: Clone and install

```bash
git clone https://github.com/dfladagermccullugh-bot/Spark.git
cd Spark
pip install -e .

# Verify it works
spark --help
```

To install development dependencies (for running tests):

```bash
pip install -e ".[dev]"
```

### Step 2: Set up Telegram

Spark communicates with you via Telegram. You need a bot token and your chat ID.

**Create a bot:**
1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to name your bot
3. Copy the **bot token** (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

**Get your chat ID:**
1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. It will reply with your **chat ID** (a number like `123456789`)

**Start a conversation with your bot:**
1. Search for your bot by the username you gave it during creation
2. Press "Start" - this is required before the bot can message you

### Step 3: Configure

```bash
cp .env.example .env
```

Edit `.env` with your keys:

```bash
SPARK_ANTHROPIC_API_KEY=sk-ant-your-key-here
SPARK_TELEGRAM_BOT_TOKEN=123456:ABC-your-token-here
SPARK_TELEGRAM_CHAT_ID=your-chat-id-here
```

Verify your configuration:

```bash
spark setup
```

### Step 4: Register a project

```bash
cd ~/projects/my-app
spark init --desc "SaaS dashboard" --goal "Finish the billing integration"
```

Or register without `cd`:

```bash
spark init ~/projects/my-app --desc "SaaS dashboard" --goal "Ship billing"
```

Spark will scan the git history, compute your work rhythm, and start tracking.

### Step 5: (Optional) Feed it knowledge

Drop articles, notes, or bookmark exports into your knowledge folder (`~/knowledge` by default), or import directly:

```bash
# Chrome bookmarks (usually at ~/.config/google-chrome/Default/Bookmarks)
spark import-bookmarks ~/path/to/Bookmarks

# Firefox bookmarks (export from Library > Bookmarks > Show All Bookmarks > Import/Backup)
spark import-bookmarks ~/path/to/bookmarks.json

# YouTube liked videos (from Google Takeout)
spark import-youtube ~/path/to/liked-videos.csv

# Twitter/X bookmarks (from data export)
spark import-twitter ~/path/to/bookmarks.js

# Check what's in the knowledge base
spark knowledge
spark search-knowledge "authentication best practices"
```

### Step 6: Start Spark

```bash
spark run
```

Spark runs in the foreground. It will:
- Monitor your projects for git activity and file changes
- Learn your work rhythm (commit frequency, active hours)
- Reach out via Telegram when projects stall with specific ideas
- Send daily morning digests and weekly retrospectives
- Enrich your bookmarks by fetching and summarizing URL content

To check project status without running the daemon:

```bash
spark status
```

## Configuration

All settings are via environment variables (with `SPARK_` prefix) or your `.env` file.

### Required

| Variable | Description |
|---|---|
| `SPARK_ANTHROPIC_API_KEY` | Claude API key |
| `SPARK_TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather |
| `SPARK_TELEGRAM_CHAT_ID` | Your Telegram chat ID |

### Optional

| Variable | Default | Description |
|---|---|---|
| `SPARK_PROJECTS_DIR` | `~/projects` | Folder containing your projects |
| `SPARK_KNOWLEDGE_DIR` | `~/knowledge` | Folder for articles, notes, bookmarks |
| `SPARK_DATA_DIR` | `~/.spark` | Where Spark stores its database and embeddings |
| `SPARK_TIMEZONE` | `UTC` | Your timezone (e.g., `America/New_York`) |
| `SPARK_QUIET_HOURS_START` | `22:00` | No nudges after this time |
| `SPARK_QUIET_HOURS_END` | `08:00` | Resume nudges after this time |
| `SPARK_AGENCY_LEVEL` | `suggest` | `suggest`, `light`, or `full` (see below) |
| `SPARK_MAX_DAILY_NUDGES` | `3` | Max nudge messages per day |
| `SPARK_MODEL` | `claude-sonnet-4-20250514` | Claude model to use |
| `SPARK_DAILY_DIGEST_ENABLED` | `true` | Send a morning project digest |
| `SPARK_WEEKLY_DIGEST_ENABLED` | `true` | Send a Sunday weekly retrospective |
| `SPARK_ENRICH_KNOWLEDGE` | `true` | Auto-fetch and summarize URL content |
| `SPARK_LEARN_FROM_CONVERSATIONS` | `true` | Extract preferences from your chats |

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
