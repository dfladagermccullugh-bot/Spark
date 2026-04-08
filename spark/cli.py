"""Spark CLI - the user's interface for managing the agent."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from spark.config import AgencyLevel, get_settings

app = typer.Typer(
    name="spark",
    help="Your AI co-founder. Monitors projects and keeps momentum alive.",
    no_args_is_help=True,
)
console = Console()


def _init_db_from_settings():
    """Initialize DB using current settings."""
    settings = get_settings()
    settings.ensure_dirs()
    from spark.db.connection import init_db
    init_db(settings.db_path)


@app.command()
def init(
    path: str = typer.Argument(
        ".", help="Path to the project directory (default: current directory)"
    ),
    name: str = typer.Option(None, "--name", "-n", help="Project name (default: directory name)"),
    description: str = typer.Option(None, "--desc", "-d", help="One-line project description"),
    goal: str = typer.Option(None, "--goal", "-g", help="Current project goal"),
):
    """Register a project for Spark to track."""
    _init_db_from_settings()
    from spark.db.connection import get_session
    from spark.db.models import Project
    from spark.collectors.git_collector import get_repo_info

    project_path = Path(path).resolve()
    if not project_path.exists():
        console.print(f"[red]Path does not exist: {project_path}[/red]")
        raise typer.Exit(1)

    project_name = name or project_path.name

    # Check if already registered
    with get_session() as session:
        existing = (
            session.query(Project)
            .filter(Project.local_path == str(project_path))
            .first()
        )
        if existing:
            console.print(f"[yellow]Already tracking: {existing.name}[/yellow]")
            raise typer.Exit(0)

    # Detect git info
    repo_info = get_repo_info(project_path)
    github_repo = None
    if repo_info.get("remotes", {}).get("origin"):
        origin_url = repo_info["remotes"]["origin"][0]
        # Extract owner/repo from git URL
        if "github.com" in origin_url:
            parts = origin_url.rstrip(".git").split("github.com")[-1].strip("/:")
            github_repo = parts

    # Prompt for description if not provided
    if not description:
        description = typer.prompt(
            "One-line description of this project",
            default="",
        )

    if not goal:
        goal = typer.prompt(
            "What are you currently working on?",
            default="",
        )

    with get_session() as session:
        project = Project(
            name=project_name,
            local_path=str(project_path),
            github_repo=github_repo,
            description=description or None,
            current_goal=goal or None,
        )
        session.add(project)

    console.print(f"\n[green]Tracking: {project_name}[/green]")
    console.print(f"  Path: {project_path}")
    if github_repo:
        console.print(f"  GitHub: {github_repo}")
    if description:
        console.print(f"  Description: {description}")
    if goal:
        console.print(f"  Goal: {goal}")

    # Do initial git collection
    from spark.collectors.git_collector import collect_git_activity

    settings = get_settings()
    events = collect_git_activity(settings.projects_dir)
    if events:
        console.print(f"  Collected {len(events)} existing activity events")

    # Compute initial baseline
    with get_session() as session:
        p = session.query(Project).filter(Project.local_path == str(project_path)).first()
        if p:
            from spark.core.rhythm import update_project_baselines
            profile = update_project_baselines(p.id)
            if profile.get("total_commits", 0) > 0:
                console.print(
                    f"  Rhythm: ~{profile['avg_commit_gap_hours']:.0f}h between commits, "
                    f"{profile['active_days_per_week']:.1f} active days/week"
                )

    console.print("\nSpark is now watching this project.")


@app.command()
def setup():
    """Interactive setup for Spark configuration."""
    console.print("[bold]Spark Setup[/bold]\n")

    settings = get_settings()

    console.print("Current configuration:")
    console.print(f"  Projects dir: {settings.projects_dir}")
    console.print(f"  Knowledge dir: {settings.knowledge_dir}")
    console.print(f"  Data dir: {settings.data_dir}")
    console.print(f"  Timezone: {settings.timezone}")
    console.print(f"  Quiet hours: {settings.quiet_hours_start} - {settings.quiet_hours_end}")
    console.print(f"  Agency level: {settings.agency_level.value}")
    console.print(f"  Max daily nudges: {settings.max_daily_nudges}")
    console.print(f"  Model: {settings.model}")
    console.print(f"  LLM API key: {'set' if settings.api_key else '[red]not set[/red]'}")
    console.print(f"  Telegram token: {'set' if settings.telegram_bot_token else '[red]not set[/red]'}")
    console.print(f"  Telegram chat ID: {'set' if settings.telegram_chat_id else '[red]not set[/red]'}")

    console.print("\nTo configure, set environment variables or edit your .env file.")
    console.print("See .env.example for all available options.")

    if not settings.api_key:
        console.print("\n[red]An LLM API key is required. Set one of: SPARK_ANTHROPIC_API_KEY, SPARK_OPENAI_API_KEY, SPARK_GROQ_API_KEY, etc.[/red]")
    if not settings.telegram_bot_token:
        console.print("[yellow]SPARK_TELEGRAM_BOT_TOKEN not set - no messaging delivery.[/yellow]")


@app.command()
def status():
    """Show status of all tracked projects."""
    _init_db_from_settings()
    from spark.db.connection import get_session
    from spark.db.models import Message, MessageDirection, Project

    with get_session() as session:
        projects = session.query(Project).all()

        if not projects:
            console.print("No projects tracked. Run [bold]spark init[/bold] in a project directory.")
            return

        table = Table(title="Spark Projects")
        table.add_column("Project", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Last Activity")
        table.add_column("Rhythm")
        table.add_column("Nudges Sent")

        for p in projects:
            # Last activity
            if p.last_activity_at:
                hours_ago = (datetime.utcnow() - p.last_activity_at).total_seconds() / 3600
                if hours_ago < 1:
                    activity_str = f"{hours_ago * 60:.0f}m ago"
                elif hours_ago < 48:
                    activity_str = f"{hours_ago:.0f}h ago"
                else:
                    activity_str = f"{hours_ago / 24:.0f}d ago"
            else:
                activity_str = "never"

            # Rhythm
            baseline = p.activity_baseline or {}
            avg_gap = baseline.get("avg_commit_gap_hours")
            rhythm_str = f"~{avg_gap:.0f}h" if avg_gap else "unknown"

            # Nudge count
            nudge_count = (
                session.query(Message)
                .filter(
                    Message.project_id == p.id,
                    Message.direction == MessageDirection.OUTBOUND.value,
                )
                .count()
            )

            status_style = {
                "active": "[green]active[/green]",
                "paused": "[yellow]paused[/yellow]",
                "shipped": "[blue]shipped[/blue]",
                "abandoned": "[dim]abandoned[/dim]",
            }

            table.add_row(
                p.name,
                status_style.get(p.status, p.status),
                activity_str,
                rhythm_str,
                str(nudge_count),
            )

        console.print(table)


@app.command()
def pause(
    project: str = typer.Argument(None, help="Project name (default: all)")
):
    """Pause nudges for a project (or all projects)."""
    _init_db_from_settings()
    from spark.db.connection import get_session
    from spark.db.models import Project, ProjectStatus

    with get_session() as session:
        if project:
            p = session.query(Project).filter(Project.name == project).first()
            if not p:
                console.print(f"[red]Project not found: {project}[/red]")
                raise typer.Exit(1)
            p.status = ProjectStatus.PAUSED.value
            console.print(f"Paused [cyan]{p.name}[/cyan]")
        else:
            active = session.query(Project).filter(
                Project.status == ProjectStatus.ACTIVE.value
            ).all()
            for p in active:
                p.status = ProjectStatus.PAUSED.value
            console.print(f"Paused {len(active)} project(s)")


@app.command()
def resume(
    project: str = typer.Argument(None, help="Project name (default: all)")
):
    """Resume nudges for a project (or all projects)."""
    _init_db_from_settings()
    from spark.db.connection import get_session
    from spark.db.models import Project, ProjectStatus

    with get_session() as session:
        if project:
            p = session.query(Project).filter(Project.name == project).first()
            if not p:
                console.print(f"[red]Project not found: {project}[/red]")
                raise typer.Exit(1)
            p.status = ProjectStatus.ACTIVE.value
            console.print(f"Resumed [cyan]{p.name}[/cyan]")
        else:
            paused = session.query(Project).filter(
                Project.status == ProjectStatus.PAUSED.value
            ).all()
            for p in paused:
                p.status = ProjectStatus.ACTIVE.value
            console.print(f"Resumed {len(paused)} project(s)")


@app.command()
def run():
    """Start the Spark daemon (foreground)."""
    settings = get_settings()

    if not settings.api_key:
        console.print("[red]An LLM API key is required. Run `spark setup` for help.[/red]")
        raise typer.Exit(1)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    console.print("[bold green]Starting Spark...[/bold green]")
    console.print(f"  Model: {settings.model}")
    console.print(f"  Projects: {settings.projects_dir}")
    console.print(f"  Knowledge: {settings.knowledge_dir}")
    console.print(f"  Check interval: {settings.stall_check_interval_minutes}m")
    console.print(f"  Quiet hours: {settings.quiet_hours_start} - {settings.quiet_hours_end}")
    console.print(f"  Agency level: {settings.agency_level.value}")
    if not settings.telegram_bot_token:
        console.print("  [yellow]Telegram: not configured (set SPARK_TELEGRAM_BOT_TOKEN)[/yellow]")
    console.print()

    from spark.daemon import run_daemon
    asyncio.run(run_daemon(settings))


@app.command()
def goal(
    project: str = typer.Argument(..., help="Project name"),
    text: str = typer.Argument(..., help="New goal description"),
):
    """Update a project's current goal."""
    _init_db_from_settings()
    from spark.db.connection import get_session
    from spark.db.models import Project

    with get_session() as session:
        p = session.query(Project).filter(Project.name == project).first()
        if not p:
            console.print(f"[red]Project not found: {project}[/red]")
            raise typer.Exit(1)
        p.current_goal = text
        console.print(f"Updated goal for [cyan]{p.name}[/cyan]: {text}")


@app.command(name="do")
def do_task(
    instruction: str = typer.Argument(..., help="What to do (e.g., 'stub out the auth endpoint')"),
    project: str = typer.Option(None, "--project", "-p", help="Project name (default: most recent)"),
):
    """Ask Spark to do work on a project (write code, create files, etc.)."""
    _init_db_from_settings()
    settings = get_settings()

    if not settings.api_key:
        console.print("[red]An LLM API key is required. Run `spark setup` for help.[/red]")
        raise typer.Exit(1)

    from spark.db.connection import get_session
    from spark.db.models import Project, ProjectStatus
    from spark.knowledge.indexer import init_chromadb
    from spark.actions.code_generator import generate_code
    from spark.actions.github_ops import create_contribution

    init_chromadb(settings.chromadb_path)

    with get_session() as session:
        if project:
            p = session.query(Project).filter(Project.name == project).first()
        else:
            p = (
                session.query(Project)
                .filter(Project.status == ProjectStatus.ACTIVE.value)
                .order_by(Project.last_activity_at.desc())
                .first()
            )

        if not p:
            console.print("[red]No project found.[/red]")
            raise typer.Exit(1)

        project_id = p.id
        project_name = p.name

    console.print(f"Working on [cyan]{project_name}[/cyan]: {instruction}\n")

    with console.status("Generating code..."):
        result = generate_code(
            project_id=project_id,
            instruction=instruction,
            api_key=settings.api_key,
            model=settings.model,
        )

    if result.success:
        console.print(f"[green]Done![/green] Changed {len(result.files_changed)} file(s):")
        for f in result.files_changed:
            console.print(f"  {f}")
        if result.summary:
            console.print(f"\n{result.summary[:500]}")

        if result.files_changed and typer.confirm("\nCreate a branch and commit these changes?"):
            contrib = create_contribution(
                project_id=project_id,
                description=instruction,
                files_changed=result.files_changed,
            )
            if contrib.success:
                console.print(f"[green]{contrib.message}[/green]")
            else:
                console.print(f"[yellow]{contrib.message}[/yellow]")
    else:
        console.print(f"[red]Failed:[/red] {result.summary[:300]}")


@app.command()
def research(
    question: str = typer.Argument(..., help="Question to research"),
    project: str = typer.Option(None, "--project", "-p", help="Project context"),
):
    """Research a topic using the knowledge base and project context."""
    _init_db_from_settings()
    settings = get_settings()

    if not settings.api_key:
        console.print("[red]An LLM API key is required. Run `spark setup` for help.[/red]")
        raise typer.Exit(1)

    from spark.db.connection import get_session
    from spark.db.models import Project, ProjectStatus
    from spark.knowledge.indexer import init_chromadb
    from spark.actions.researcher import research_topic

    init_chromadb(settings.chromadb_path)

    with get_session() as session:
        if project:
            p = session.query(Project).filter(Project.name == project).first()
        else:
            p = (
                session.query(Project)
                .filter(Project.status == ProjectStatus.ACTIVE.value)
                .order_by(Project.last_activity_at.desc())
                .first()
            )

        if not p:
            console.print("[red]No project found.[/red]")
            raise typer.Exit(1)

        project_id = p.id
        project_name = p.name

    console.print(f"Researching for [cyan]{project_name}[/cyan]: {question}\n")

    with console.status("Researching..."):
        result = research_topic(
            project_id=project_id,
            question=question,
            api_key=settings.api_key,
            model=settings.model,
        )

    if result.success:
        console.print(result.summary)
        if result.findings:
            console.print(f"\n[dim]({len(result.findings)} sources referenced)[/dim]")
    else:
        console.print(f"[red]Research failed:[/red] {result.summary[:300]}")


@app.command()
def knowledge():
    """Show knowledge base stats."""
    _init_db_from_settings()
    from spark.db.connection import get_session
    from spark.db.models import KnowledgeItem

    with get_session() as session:
        items = session.query(KnowledgeItem).all()
        if not items:
            console.print("Knowledge base is empty.")
            console.print("\nDrop files into your knowledge folder or use import commands:")
            console.print("  spark import-bookmarks <file>")
            console.print("  spark import-youtube <file>")
            console.print("  spark import-twitter <file>")
            return

        table = Table(title="Knowledge Base")
        table.add_column("Type", style="cyan")
        table.add_column("Count")
        table.add_column("Indexed")

        by_type: dict[str, dict] = {}
        for item in items:
            entry = by_type.setdefault(item.source_type, {"total": 0, "indexed": 0})
            entry["total"] += 1
            if item.embedding_id:
                entry["indexed"] += 1

        for stype, counts in sorted(by_type.items()):
            table.add_row(
                stype,
                str(counts["total"]),
                str(counts["indexed"]),
            )

        console.print(table)
        console.print(f"\nTotal: {len(items)} items")


@app.command(name="import-bookmarks")
def import_bookmarks(
    file: str = typer.Argument(..., help="Path to bookmarks file (Chrome/Firefox JSON or HTML)"),
):
    """Import browser bookmarks from an export file."""
    _init_db_from_settings()
    from spark.knowledge.feeds import import_chrome_bookmarks, import_firefox_bookmarks

    path = Path(file).resolve()
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        raise typer.Exit(1)

    # Try Chrome format first, then Firefox
    import json
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "roots" in data:
            count = import_chrome_bookmarks(path)
            console.print(f"[green]Imported {count} Chrome bookmarks[/green]")
        else:
            count = import_firefox_bookmarks(path)
            console.print(f"[green]Imported {count} Firefox bookmarks[/green]")
    except json.JSONDecodeError:
        # Try HTML bookmark format via ingester
        from spark.knowledge.ingester import ingest_file
        from spark.db.connection import get_session
        from spark.db.models import KnowledgeItem

        items = ingest_file(path)
        with get_session() as session:
            for item in items:
                session.add(item)
        console.print(f"[green]Imported {len(items)} bookmarks from HTML[/green]")

    _run_index()


@app.command(name="import-youtube")
def import_youtube(
    file: str = typer.Argument(..., help="Path to YouTube export (CSV, JSON, or HTML)"),
):
    """Import YouTube likes/history from a Google Takeout export."""
    _init_db_from_settings()
    from spark.knowledge.feeds import import_youtube_takeout

    path = Path(file).resolve()
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        raise typer.Exit(1)

    count = import_youtube_takeout(path)
    console.print(f"[green]Imported {count} YouTube items[/green]")
    _run_index()


@app.command(name="import-twitter")
def import_twitter(
    file: str = typer.Argument(..., help="Path to Twitter/X bookmarks export"),
):
    """Import Twitter/X bookmarks from a data export."""
    _init_db_from_settings()
    from spark.knowledge.feeds import import_twitter_bookmarks

    path = Path(file).resolve()
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        raise typer.Exit(1)

    count = import_twitter_bookmarks(path)
    console.print(f"[green]Imported {count} Twitter bookmarks[/green]")
    _run_index()


@app.command(name="search-knowledge")
def search_knowledge_cmd(
    query: str = typer.Argument(..., help="Search query"),
    n: int = typer.Option(5, "--results", "-n", help="Number of results"),
):
    """Search your knowledge base."""
    _init_db_from_settings()
    settings = get_settings()
    from spark.knowledge.indexer import init_chromadb, search_knowledge

    init_chromadb(settings.chromadb_path)

    results = search_knowledge(query, n_results=n)
    if not results:
        console.print("No results found. Make sure your knowledge base is indexed.")
        return

    for i, r in enumerate(results, 1):
        dist = f" (distance: {r['distance']:.2f})" if r.get('distance') is not None else ""
        console.print(f"\n[bold]{i}. {r['title']}[/bold]{dist}")
        console.print(f"   Type: {r['source_type']}")
        if r.get("source_url"):
            console.print(f"   URL: {r['source_url']}")
        if r.get("content"):
            preview = r["content"][:150].replace("\n", " ")
            console.print(f"   {preview}")


@app.command()
def digest():
    """Get a project digest right now."""
    _init_db_from_settings()
    settings = get_settings()

    if not settings.api_key:
        console.print("[red]An LLM API key is required. Run `spark setup` for help.[/red]")
        raise typer.Exit(1)

    from spark.knowledge.indexer import init_chromadb
    from spark.core.digest import generate_daily_digest

    init_chromadb(settings.chromadb_path)

    with console.status("Generating digest..."):
        text = generate_daily_digest(
            api_key=settings.api_key,
            model=settings.model,
        )

    if text:
        console.print(text)
    else:
        console.print("[yellow]No digest generated (maybe already sent today, or no projects tracked).[/yellow]")


@app.command()
def memories():
    """Show what Spark has learned about you."""
    _init_db_from_settings()
    from spark.core.memory import recall_memories

    mems = recall_memories(limit=20)
    if not mems:
        console.print("Spark hasn't learned anything specific yet.")
        console.print("Keep interacting - it picks up on your preferences over time.")
        return

    table = Table(title="What Spark Knows About You")
    table.add_column("Type", style="cyan")
    table.add_column("Memory")
    table.add_column("Learned", style="dim")

    for m in mems:
        table.add_row(m["type"], m["content"], m.get("created_at", "")[:10])

    console.print(table)


@app.command()
def effectiveness():
    """Show nudge effectiveness statistics."""
    _init_db_from_settings()
    from spark.core.feedback import get_effectiveness_stats

    stats = get_effectiveness_stats()

    if stats["total_nudges"] == 0:
        console.print("No nudge data yet. Run the daemon and let Spark send some nudges first.")
        return

    table = Table(title="Nudge Effectiveness")
    table.add_column("Metric", style="cyan")
    table.add_column("Value")

    rate = stats["effectiveness_rate"] * 100
    reply_rate = stats["reply_rate"] * 100

    table.add_row("Total nudges", str(stats["total_nudges"]))
    table.add_row("Effective", f"{stats['effective_count']} ({rate:.0f}%)")
    table.add_row("No action", str(stats["ineffective_count"]))
    table.add_row("Pending", str(stats["pending_count"]))
    table.add_row("Avg time to action", f"{stats['avg_hours_to_action']:.1f}h")
    table.add_row("Reply rate", f"{reply_rate:.0f}%")

    console.print(table)

    by_type = stats.get("by_type", {})
    if by_type:
        type_table = Table(title="By Nudge Type")
        type_table.add_column("Type", style="cyan")
        type_table.add_column("Effective")
        type_table.add_column("Total")
        type_table.add_column("Rate")

        for ntype, data in by_type.items():
            type_table.add_row(
                ntype,
                str(data["effective"]),
                str(data["total"]),
                f"{data['rate'] * 100:.0f}%",
            )

        console.print(type_table)


@app.command(name="enrich")
def enrich_cmd(
    batch: int = typer.Option(5, "--batch", "-b", help="Number of items to enrich per run"),
):
    """Fetch and summarize URL content for knowledge items."""
    _init_db_from_settings()
    settings = get_settings()

    if not settings.api_key:
        console.print("[red]An LLM API key is required. Run `spark setup` for help.[/red]")
        raise typer.Exit(1)

    from spark.knowledge.enricher import enrich_knowledge_items

    with console.status("Enriching knowledge items..."):
        enriched = enrich_knowledge_items(
            api_key=settings.api_key,
            model=settings.model,
            batch_size=batch,
        )

    if enriched:
        console.print(f"[green]Enriched {enriched} knowledge item(s) with content summaries[/green]")
    else:
        console.print("No items to enrich (all URLs already processed or no URLs found).")


def _run_index():
    """Index newly imported items into ChromaDB."""
    settings = get_settings()
    from spark.knowledge.indexer import init_chromadb, index_knowledge_items

    init_chromadb(settings.chromadb_path)
    indexed = index_knowledge_items()
    if indexed:
        console.print(f"  Indexed {indexed} items into vector store")


if __name__ == "__main__":
    app()
