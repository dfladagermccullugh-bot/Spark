"""Spark daemon - the main event loop that orchestrates everything."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from spark.collectors.file_watcher import SparkFileWatcher
from spark.collectors.git_collector import collect_git_activity
from spark.config import SparkSettings
from spark.core.context_engine import build_cross_project_context
from spark.core.nudge_generator import generate_nudge, generate_reply
from spark.core.rhythm import update_project_baselines
from spark.core.stall_detector import detect_stalls
from spark.db.connection import get_session, init_db
from spark.db.models import Message, MessageDirection, Project, ProjectStatus

logger = logging.getLogger(__name__)


class SparkDaemon:
    """Main Spark daemon that runs the agent loop."""

    def __init__(self, settings: SparkSettings):
        self.settings = settings
        self._scheduler = AsyncIOScheduler()
        self._file_watcher: SparkFileWatcher | None = None
        self._delivery = None
        self._running = False

    async def start(self) -> None:
        """Start the Spark daemon."""
        logger.info("Starting Spark daemon...")

        # Initialize database
        self.settings.ensure_dirs()
        init_db(self.settings.db_path)

        # Initialize delivery adapter
        if self.settings.telegram_bot_token and self.settings.telegram_chat_id:
            from spark.delivery.telegram import TelegramAdapter

            self._delivery = TelegramAdapter(
                bot_token=self.settings.telegram_bot_token,
                chat_id=self.settings.telegram_chat_id,
            )
            await self._delivery.start_listening(on_message=self._handle_incoming)
            logger.info("Telegram delivery adapter started")
        else:
            logger.warning("No delivery adapter configured (set SPARK_TELEGRAM_BOT_TOKEN)")

        # Start file watcher
        self._file_watcher = SparkFileWatcher(
            projects_dir=self.settings.projects_dir,
            knowledge_dir=self.settings.knowledge_dir,
            on_project_change=self._on_project_change,
            on_new_knowledge=self._on_new_knowledge,
        )
        self._file_watcher.start()

        # Schedule recurring jobs
        self._scheduler.add_job(
            self._collect_activity,
            "interval",
            minutes=self.settings.stall_check_interval_minutes,
            id="collect_activity",
            next_run_time=datetime.utcnow(),
        )
        self._scheduler.add_job(
            self._check_stalls,
            "interval",
            minutes=self.settings.stall_check_interval_minutes,
            id="check_stalls",
        )
        self._scheduler.add_job(
            self._update_baselines,
            "interval",
            hours=6,
            id="update_baselines",
        )
        self._scheduler.start()

        self._running = True
        logger.info("Spark daemon is running")

        # Keep running until stopped
        try:
            while self._running:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            await self.stop()

    async def stop(self) -> None:
        """Stop the daemon gracefully."""
        logger.info("Stopping Spark daemon...")
        self._running = False

        if self._file_watcher:
            self._file_watcher.stop()

        if self._delivery:
            await self._delivery.stop()

        self._scheduler.shutdown(wait=False)
        logger.info("Spark daemon stopped")

    def _collect_activity(self) -> None:
        """Collect git activity from all tracked projects."""
        logger.debug("Collecting git activity...")
        new_events = collect_git_activity(self.settings.projects_dir)
        if new_events:
            logger.info(f"Collected {len(new_events)} new activity events")

    def _check_stalls(self) -> None:
        """Check for stalled projects and send nudges."""
        logger.debug("Checking for stalls...")
        stalls = detect_stalls(
            timezone=self.settings.timezone,
            quiet_start=self.settings.quiet_hours_start,
            quiet_end=self.settings.quiet_hours_end,
            min_hours_between_nudges=self.settings.min_hours_between_nudges,
            max_daily_nudges=self.settings.max_daily_nudges,
            stall_multiplier=self.settings.stall_threshold_multiplier,
        )

        if not stalls:
            logger.debug("No stalls detected")
            return

        # Generate and send a nudge for the highest-confidence stall
        stall = stalls[0]
        nudge = generate_nudge(
            stall=stall,
            api_key=self.settings.anthropic_api_key,
            model=self.settings.model,
        )

        if nudge and self._delivery:
            asyncio.get_event_loop().create_task(self._delivery.send(nudge))

    def _update_baselines(self) -> None:
        """Update rhythm baselines for all active projects."""
        logger.debug("Updating rhythm baselines...")
        with get_session() as session:
            projects = (
                session.query(Project)
                .filter(Project.status == ProjectStatus.ACTIVE.value)
                .all()
            )
            project_ids = [p.id for p in projects]

        for pid in project_ids:
            update_project_baselines(pid)

    def _on_project_change(self, file_path: str, action: str) -> None:
        """Callback when a project file changes."""
        logger.debug(f"Project file {action}: {file_path}")

    def _on_new_knowledge(self, file_path: str) -> None:
        """Callback when a new knowledge item is added."""
        logger.info(f"New knowledge item detected: {file_path}")
        # Phase 2: ingest and index the knowledge item

    def _handle_incoming(self, text: str) -> str | None:
        """Handle an incoming message from the user."""
        # Handle commands
        if text.startswith("/"):
            return self._handle_command(text)

        # Find the most recently nudged project to reply in context
        with get_session() as session:
            last_outbound = (
                session.query(Message)
                .filter(Message.direction == MessageDirection.OUTBOUND.value)
                .order_by(Message.sent_at.desc())
                .first()
            )
            project_id = last_outbound.project_id if last_outbound else None

        if not project_id:
            return "Hey! I don't have context on which project you're referring to. Try /projects to see what I'm tracking."

        reply = generate_reply(
            project_id=project_id,
            user_message=text,
            api_key=self.settings.anthropic_api_key,
            model=self.settings.model,
        )
        return reply

    def _handle_command(self, command: str) -> str:
        """Handle slash commands from the messaging platform."""
        cmd = command.strip().split()[0].lower()

        if cmd == "/status":
            return self._cmd_status()
        elif cmd == "/projects":
            return self._cmd_projects()
        elif cmd == "/pause":
            return self._cmd_pause()
        elif cmd == "/resume":
            return self._cmd_resume()
        else:
            return f"Unknown command: {cmd}\n\nAvailable: /status, /projects, /pause, /resume"

    def _cmd_status(self) -> str:
        summaries = build_cross_project_context()
        if not summaries:
            return "No projects tracked yet. Use `spark init` in a project directory to get started."

        lines = ["Here's where things stand:\n"]
        for p in summaries:
            hours = p.get("hours_since_activity")
            time_str = f"{hours:.0f}h ago" if hours else "never"
            lines.append(f"  {p['name']} [{p['status']}] - last activity: {time_str}")
            if p.get("current_goal"):
                lines.append(f"    Goal: {p['current_goal']}")
        return "\n".join(lines)

    def _cmd_projects(self) -> str:
        with get_session() as session:
            projects = session.query(Project).all()
            if not projects:
                return "No projects tracked. Use `spark init` in a project directory."
            lines = ["Tracked projects:\n"]
            for p in projects:
                lines.append(f"  {p.name} [{p.status}] - {p.local_path}")
            return "\n".join(lines)

    def _cmd_pause(self) -> str:
        with get_session() as session:
            active = (
                session.query(Project)
                .filter(Project.status == ProjectStatus.ACTIVE.value)
                .all()
            )
            for p in active:
                p.status = ProjectStatus.PAUSED.value
            count = len(active)
        return f"Paused {count} project(s). I'll be quiet until you /resume."

    def _cmd_resume(self) -> str:
        with get_session() as session:
            paused = (
                session.query(Project)
                .filter(Project.status == ProjectStatus.PAUSED.value)
                .all()
            )
            for p in paused:
                p.status = ProjectStatus.ACTIVE.value
            count = len(paused)
        return f"Resumed {count} project(s). Back in action."


async def run_daemon(settings: SparkSettings) -> None:
    """Entry point for running the daemon."""
    daemon = SparkDaemon(settings)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(daemon.stop()))

    await daemon.start()
