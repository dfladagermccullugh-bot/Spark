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
    console.print(f"  Anthropic key: {'set' if settings.anthropic_api_key else '[red]not set[/red]'}")
    console.print(f"  Telegram token: {'set' if settings.telegram_bot_token else '[red]not set[/red]'}")
    console.print(f"  Telegram chat ID: {'set' if settings.telegram_chat_id else '[red]not set[/red]'}")

    console.print("\nTo configure, set environment variables or edit your .env file.")
    console.print("See .env.example for all available options.")

    if not settings.anthropic_api_key:
        console.print("\n[red]SPARK_ANTHROPIC_API_KEY is required.[/red]")
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

    if not settings.anthropic_api_key:
        console.print("[red]SPARK_ANTHROPIC_API_KEY is required. Run `spark setup` for help.[/red]")
        raise typer.Exit(1)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    console.print("[bold green]Starting Spark...[/bold green]")
    console.print(f"  Projects: {settings.projects_dir}")
    console.print(f"  Knowledge: {settings.knowledge_dir}")
    console.print(f"  Check interval: {settings.stall_check_interval_minutes}m")
    console.print(f"  Quiet hours: {settings.quiet_hours_start} - {settings.quiet_hours_end}")
    console.print(f"  Agency level: {settings.agency_level.value}")
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


if __name__ == "__main__":
    app()
