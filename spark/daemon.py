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
from spark.config import RETIRED_MODELS, SparkSettings
from spark.core.context_engine import build_cross_project_context
from spark.core import llm
from spark.core.alerts import AlertLimiter, format_alert
from spark.core.digest import generate_daily_digest, generate_weekly_digest
from spark.core.feedback import check_nudge_effectiveness, get_effectiveness_stats
from spark.core.llm import LLMError
from spark.core.memory import process_conversation_for_memories, recall_memories
from spark.core.nudge_generator import generate_nudge, generate_reply
from spark.core.rhythm import update_project_baselines
from spark.core.stall_detector import detect_stalls
from spark.db.connection import get_session, init_db
from spark.db.models import KnowledgeItem, Message, MessageDirection, Project, ProjectStatus
from spark.knowledge.connector import update_relevance_scores
from spark.knowledge.enricher import enrich_knowledge_items
from spark.knowledge.feeds import auto_detect_and_import
from spark.knowledge.indexer import (
    index_knowledge_items,
    index_project_files,
    init_chromadb,
)
from spark.knowledge.ingester import scan_knowledge_folder
from spark.actions.authorization import (
    _load_pending_from_db,
    approve_latest,
    clear_expired,
    format_proposal_message,
    get_pending_proposals,
    needs_approval,
    propose_action,
    reject_latest,
)
from spark.actions.code_generator import generate_code
from spark.actions.github_ops import create_contribution
from spark.actions.researcher import analyze_blocker, research_topic
from spark.config import AgencyLevel

logger = logging.getLogger(__name__)


class SparkDaemon:
    """Main Spark daemon that runs the agent loop."""

    def __init__(self, settings: SparkSettings):
        self.settings = settings
        self._scheduler = AsyncIOScheduler()
        self._file_watcher: SparkFileWatcher | None = None
        self._delivery = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._alerts = AlertLimiter(settings.data_dir / "alert_state.json")
        llm.configure(settings)

    async def start(self) -> None:
        """Start the Spark daemon."""
        logger.info("Starting Spark daemon...")
        self._loop = asyncio.get_running_loop()

        # Initialize database and vector store
        self.settings.ensure_dirs()
        init_db(self.settings.db_path)
        init_chromadb(self.settings.chromadb_path)

        # Restore pending proposals from database
        _load_pending_from_db()

        # Initialize delivery adapter
        if self.settings.dry_run:
            from spark.delivery.dry_run import DryRunAdapter

            self._delivery = DryRunAdapter(self.settings.dry_run_path)
            await self._delivery.start_listening(on_message=self._handle_incoming)
            logger.warning(
                "DRY RUN: messages are printed and written to %s, not sent to Telegram",
                self.settings.dry_run_path,
            )
        elif self.settings.telegram_bot_token and self.settings.telegram_chat_id:
            from spark.delivery.telegram import TelegramAdapter

            self._delivery = TelegramAdapter(
                bot_token=self.settings.telegram_bot_token,
                chat_id=self.settings.telegram_chat_id,
            )
            await self._delivery.start_listening(on_message=self._handle_incoming)
            logger.info("Telegram delivery adapter started")
        else:
            logger.warning("No delivery adapter configured (set SPARK_TELEGRAM_BOT_TOKEN)")

        # Fail loudly at startup if the model/auth is broken
        await asyncio.to_thread(self._startup_check)

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
        self._scheduler.add_job(
            self._ingest_and_index_knowledge,
            "interval",
            minutes=15,
            id="ingest_knowledge",
            next_run_time=datetime.utcnow(),
        )
        self._scheduler.add_job(
            self._update_relevance,
            "interval",
            hours=3,
            id="update_relevance",
        )
        # Phase 4: Learning & intelligence jobs
        self._scheduler.add_job(
            self._check_feedback,
            "interval",
            hours=1,
            id="check_feedback",
        )
        self._scheduler.add_job(
            self._extract_memories,
            "interval",
            hours=2,
            id="extract_memories",
        )
        self._scheduler.add_job(
            self._enrich_knowledge,
            "interval",
            hours=1,
            id="enrich_knowledge",
        )
        self._scheduler.add_job(
            self._send_daily_digest,
            "cron",
            hour=int(self.settings.quiet_hours_end.split(":")[0]),
            minute=30,
            id="daily_digest",
        )
        self._scheduler.add_job(
            self._send_weekly_digest,
            "cron",
            day_of_week="sun",
            hour=10,
            id="weekly_digest",
        )
        self._scheduler.add_job(
            self._clear_expired_proposals,
            "interval",
            hours=6,
            id="clear_expired",
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

    # ------------------------------------------------------------------
    # LLM failure handling
    # ------------------------------------------------------------------

    def _startup_check(self) -> bool:
        """Verify the model works; log at ERROR and alert the owner if not."""
        model = self.settings.model
        try:
            if model in RETIRED_MODELS:
                raise LLMError(
                    f"Model {model!r} has been retired by Anthropic; set SPARK_MODEL "
                    "to a current model",
                    model=model,
                    error_type="RetiredModel",
                )
            if not self.settings.llm_configured:
                raise LLMError(
                    "No LLM configured (set SPARK_ANTHROPIC_API_KEY or "
                    "SPARK_LLM_BACKEND=claude-cli)",
                    model=model,
                    error_type="MissingAPIKey",
                )
            result = llm.ping(self.settings.anthropic_api_key, model)
            logger.info(
                "LLM startup check OK (model=%s, stop_reason=%s, %.1fs)",
                model, result.stop_reason, result.latency_s,
            )
            return True
        except LLMError as err:
            logger.error("=" * 70)
            logger.error("STARTUP CHECK FAILED: Claude is not usable: %s", err, exc_info=err)
            logger.error("Nudges, digests and replies will NOT work until this is fixed.")
            logger.error("=" * 70)
            self._alert_llm_failure(err, log=False)
            return False

    def _alert_llm_failure(self, err: LLMError, log: bool = True) -> None:
        """Log an LLM failure at ERROR and (rate-limited) tell the owner via delivery."""
        if log:
            logger.error("Claude call failed: %s", err, exc_info=err)
        if self._delivery is None:
            return
        if not self._alerts.should_send(err.error_type):
            logger.info("LLM failure alert suppressed (already alerted for %s)", err.error_type)
            return
        self._send(format_alert(err))

    def _send(self, text: str) -> None:
        """Send via the delivery adapter from either the event loop or a worker thread."""
        if not self._delivery:
            return
        try:
            asyncio.get_running_loop()
            asyncio.ensure_future(self._delivery.send(text))
        except RuntimeError:
            # Scheduler jobs run in worker threads: hand off to the daemon's loop.
            if self._loop is None:
                logger.error("Cannot send message: daemon event loop not running")
                return
            future = asyncio.run_coroutine_threadsafe(self._delivery.send(text), self._loop)
            future.add_done_callback(self._log_send_result)

    @staticmethod
    def _log_send_result(future) -> None:
        exc = future.exception()
        if exc is not None:
            logger.error("Message delivery failed", exc_info=exc)

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
        try:
            nudge = generate_nudge(
                stall=stall,
                api_key=self.settings.anthropic_api_key,
                model=self.settings.model,
                agency_level=self.settings.agency_level.value,
            )
        except LLMError as err:
            self._alert_llm_failure(err)
            return

        if nudge:
            self._send(nudge)

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
        from pathlib import Path

        # Try auto-detecting external feed exports
        path = Path(file_path)
        imported = auto_detect_and_import(path)
        if imported:
            logger.info(f"Auto-imported {imported} items from {path.name}")

        # Run a quick ingest + index cycle
        self._ingest_and_index_knowledge()

    def _ingest_and_index_knowledge(self) -> None:
        """Scan knowledge folder, ingest new items, and index them."""
        logger.debug("Ingesting knowledge...")
        new_items = scan_knowledge_folder(self.settings.knowledge_dir)
        if new_items:
            logger.info(f"Ingested {len(new_items)} new knowledge items")

        indexed = index_knowledge_items()
        if indexed:
            logger.info(f"Indexed {indexed} knowledge items into vector store")

        # Also index project files
        with get_session() as session:
            projects = (
                session.query(Project)
                .filter(Project.status == ProjectStatus.ACTIVE.value)
                .all()
            )
            project_data = [(p.id, p.local_path) for p in projects]

        for pid, ppath in project_data:
            index_project_files(pid, ppath)

    def _update_relevance(self) -> None:
        """Update relevance scores between knowledge items and projects."""
        logger.debug("Updating knowledge relevance scores...")
        updated = update_relevance_scores()
        if updated:
            logger.info(f"Updated relevance scores for {updated} items")

    def _check_feedback(self) -> None:
        """Check nudge effectiveness based on resumed activity."""
        logger.debug("Checking nudge feedback...")
        updated = check_nudge_effectiveness()
        if updated:
            logger.info(f"Updated feedback for {updated} nudges")

    def _extract_memories(self) -> None:
        """Extract memories from recent conversations."""
        if not self.settings.llm_configured:
            return
        logger.debug("Extracting memories from conversations...")
        try:
            stored = process_conversation_for_memories(
                api_key=self.settings.anthropic_api_key,
                model=self.settings.model,
            )
        except LLMError as err:
            self._alert_llm_failure(err)
            return
        if stored:
            logger.info(f"Extracted {stored} new memories")

    def _enrich_knowledge(self) -> None:
        """Fetch and summarize URL content for knowledge items."""
        if not self.settings.llm_configured:
            return
        logger.debug("Enriching knowledge items...")
        try:
            enriched = enrich_knowledge_items(
                api_key=self.settings.anthropic_api_key,
                model=self.settings.model,
                batch_size=3,
            )
        except LLMError as err:
            self._alert_llm_failure(err)
            return
        if enriched:
            logger.info(f"Enriched {enriched} knowledge items")

    def _send_daily_digest(self) -> None:
        """Send the daily project digest."""
        if not self.settings.llm_configured or not self._delivery:
            return
        logger.info("Generating daily digest...")
        try:
            digest = generate_daily_digest(
                api_key=self.settings.anthropic_api_key,
                model=self.settings.model,
            )
        except LLMError as err:
            self._alert_llm_failure(err)
            return
        if digest:
            self._send(digest)

    def _send_weekly_digest(self) -> None:
        """Send the weekly retrospective digest."""
        if not self.settings.llm_configured or not self._delivery:
            return
        logger.info("Generating weekly digest...")
        try:
            digest = generate_weekly_digest(
                api_key=self.settings.anthropic_api_key,
                model=self.settings.model,
            )
        except LLMError as err:
            self._alert_llm_failure(err)
            return
        if digest:
            self._send(digest)

    def _clear_expired_proposals(self) -> None:
        """Clear proposals that have been pending too long."""
        cleared = clear_expired(max_age_hours=24.0)
        if cleared:
            logger.info(f"Cleared {cleared} expired proposals")

    def _handle_incoming(self, text: str) -> str | None:
        """Handle an incoming message from the user."""
        # Handle commands
        if text.startswith("/"):
            return self._handle_command(text)

        normalized = text.strip().lower()

        # Handle action approval/rejection
        if normalized in ("go", "yes", "approve", "do it", "ship it"):
            return self._handle_approval()
        if normalized in ("skip", "no", "nah", "pass", "reject"):
            return self._handle_rejection()

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

        try:
            return generate_reply(
                project_id=project_id,
                user_message=text,
                api_key=self.settings.anthropic_api_key,
                model=self.settings.model,
            )
        except LLMError as err:
            logger.error("Claude call failed while replying: %s", err, exc_info=err)
            # The reply itself is the notice to the owner; no separate alert needed.
            return format_alert(err)

    def _handle_approval(self) -> str:
        """Handle user approving a pending action."""
        proposal = approve_latest()
        if not proposal:
            return "Nothing pending to approve."

        # Execute the approved action
        return self._execute_action(proposal)

    def _handle_rejection(self) -> str:
        """Handle user rejecting a pending action."""
        proposal = reject_latest()
        if not proposal:
            return "Nothing pending to skip."
        return f"Skipped. I'll keep thinking about {proposal.project_name}."

    def _execute_action(self, proposal) -> str:
        """Execute an approved action proposal."""
        from spark.db.models import TaskType

        if proposal.action_type == TaskType.CODE_GEN.value:
            result = generate_code(
                project_id=proposal.project_id,
                instruction=proposal.description,
                api_key=self.settings.anthropic_api_key,
                model=self.settings.model,
            )
            if result.success:
                # If we have files changed, offer to create a branch
                files_str = ", ".join(result.files_changed[:5])
                msg = f"Done! Changed: {files_str}\n\n{result.summary[:300]}"

                if result.files_changed:
                    contrib = create_contribution(
                        project_id=proposal.project_id,
                        description=proposal.description,
                        files_changed=result.files_changed,
                    )
                    if contrib.success:
                        msg += f"\n\nPushed to branch: {contrib.details.get('branch', '?')}"
                    else:
                        msg += f"\n\nChanges are local (push failed: {contrib.message})"

                return msg
            else:
                return f"Couldn't complete that: {result.summary[:200]}"

        elif proposal.action_type == TaskType.RESEARCH.value:
            result = research_topic(
                project_id=proposal.project_id,
                question=proposal.description,
                api_key=self.settings.anthropic_api_key,
                model=self.settings.model,
            )
            if result.success:
                return result.summary[:1000]
            else:
                return f"Research didn't turn up much: {result.summary[:200]}"

        return f"Executed: {proposal.description}"

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
        elif cmd == "/knowledge":
            return self._cmd_knowledge()
        elif cmd == "/do":
            return self._cmd_do(command)
        elif cmd == "/research":
            return self._cmd_research(command)
        elif cmd == "/pending":
            return self._cmd_pending()
        elif cmd == "/digest":
            return self._cmd_digest()
        elif cmd == "/memories":
            return self._cmd_memories()
        elif cmd == "/effectiveness":
            return self._cmd_effectiveness()
        else:
            return (
                f"Unknown command: {cmd}\n\n"
                "Available:\n"
                "  /status - Project overview\n"
                "  /projects - List projects\n"
                "  /knowledge - Knowledge base stats\n"
                "  /do <task> - Ask Spark to do something\n"
                "  /research <question> - Research a topic\n"
                "  /pending - Show pending proposals\n"
                "  /digest - Get a project digest now\n"
                "  /memories - What Spark has learned about you\n"
                "  /effectiveness - Nudge effectiveness stats\n"
                "  /pause - Silence Spark\n"
                "  /resume - Resume nudges"
            )

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


    def _cmd_do(self, command: str) -> str:
        """Handle /do <task> - ask Spark to do work on a project."""
        parts = command.strip().split(maxsplit=1)
        if len(parts) < 2:
            return "Usage: /do <what to do>\nExample: /do stub out the auth endpoint"

        instruction = parts[1]

        # Find the most active/recently nudged project
        with get_session() as session:
            last_msg = (
                session.query(Message)
                .filter(Message.direction == MessageDirection.OUTBOUND.value)
                .order_by(Message.sent_at.desc())
                .first()
            )
            if last_msg and last_msg.project_id:
                project = session.query(Project).filter(Project.id == last_msg.project_id).first()
            else:
                project = (
                    session.query(Project)
                    .filter(Project.status == ProjectStatus.ACTIVE.value)
                    .order_by(Project.last_activity_at.desc())
                    .first()
                )

            if not project:
                return "No active projects. Use `spark init` to register one."

            project_id = project.id
            project_name = project.name

        from spark.db.models import TaskType

        # Check if approval is needed
        if needs_approval(self.settings.agency_level, TaskType.CODE_GEN.value):
            proposal = propose_action(
                project_id=project_id,
                project_name=project_name,
                action_type=TaskType.CODE_GEN.value,
                description=instruction,
            )
            return format_proposal_message(proposal)
        else:
            # Execute directly
            result = generate_code(
                project_id=project_id,
                instruction=instruction,
                api_key=self.settings.anthropic_api_key,
                model=self.settings.model,
            )
            if result.success:
                files_str = ", ".join(result.files_changed[:5])
                msg = f"Done! Changed: {files_str}\n\n{result.summary[:300]}"
                if result.files_changed:
                    contrib = create_contribution(
                        project_id=project_id,
                        description=instruction,
                        files_changed=result.files_changed,
                    )
                    if contrib.success:
                        msg += f"\n\nPushed to branch: {contrib.details.get('branch', '?')}"
                return msg
            else:
                return f"Couldn't do that: {result.summary[:200]}"

    def _cmd_research(self, command: str) -> str:
        """Handle /research <question> - research a topic."""
        parts = command.strip().split(maxsplit=1)
        if len(parts) < 2:
            return "Usage: /research <question>\nExample: /research best approach for auth tokens"

        question = parts[1]

        with get_session() as session:
            project = (
                session.query(Project)
                .filter(Project.status == ProjectStatus.ACTIVE.value)
                .order_by(Project.last_activity_at.desc())
                .first()
            )
            if not project:
                return "No active projects to research against."
            project_id = project.id

        result = research_topic(
            project_id=project_id,
            question=question,
            api_key=self.settings.anthropic_api_key,
            model=self.settings.model,
        )
        if result.success:
            return result.summary[:1000]
        return f"Research didn't work out: {result.summary[:200]}"

    def _cmd_pending(self) -> str:
        """Show pending action proposals."""
        pending = get_pending_proposals()
        if not pending:
            return "No pending proposals."
        lines = ["Pending proposals:\n"]
        for i, p in enumerate(pending, 1):
            lines.append(f"  {i}. [{p.action_type}] {p.project_name}: {p.description}")
        lines.append("\nReply 'go' to approve the latest, or 'skip' to reject.")
        return "\n".join(lines)

    def _cmd_knowledge(self) -> str:
        with get_session() as session:
            total = session.query(KnowledgeItem).count()
            indexed = session.query(KnowledgeItem).filter(
                KnowledgeItem.embedding_id.isnot(None)
            ).count()
            by_type = {}
            for item in session.query(KnowledgeItem).all():
                by_type[item.source_type] = by_type.get(item.source_type, 0) + 1

        if total == 0:
            return (
                "No knowledge items yet.\n\n"
                "Drop files into your knowledge folder, or use:\n"
                "  spark import-bookmarks <file>\n"
                "  spark import-youtube <file>\n"
                "  spark import-twitter <file>"
            )

        lines = [f"Knowledge base: {total} items ({indexed} indexed)\n"]
        for stype, count in sorted(by_type.items()):
            lines.append(f"  {stype}: {count}")
        return "\n".join(lines)

    def _cmd_digest(self) -> str:
        """Generate and return a digest on demand."""
        if not self.settings.llm_configured:
            return "API key not configured."

        try:
            digest = generate_daily_digest(
                api_key=self.settings.anthropic_api_key,
                model=self.settings.model,
            )
        except LLMError as err:
            logger.error("Claude call failed while generating digest: %s", err, exc_info=err)
            return format_alert(err)
        if digest:
            return digest
        return "Couldn't generate a digest right now. Maybe one was already sent today."

    def _cmd_memories(self) -> str:
        """Show what Spark has learned about the user."""
        memories = recall_memories(limit=15)
        if not memories:
            return "I haven't learned anything specific about you yet. Keep chatting - I'll pick up on your preferences over time."

        lines = ["Here's what I've learned about you:\n"]
        for m in memories:
            lines.append(f"  [{m['type']}] {m['content']}")
        return "\n".join(lines)

    def _cmd_effectiveness(self) -> str:
        """Show nudge effectiveness stats."""
        stats = get_effectiveness_stats()
        if stats["total_nudges"] == 0:
            return "No nudge data yet. I need to send a few nudges before I can track effectiveness."

        rate = stats["effectiveness_rate"] * 100
        reply_rate = stats["reply_rate"] * 100
        lines = [
            "Nudge effectiveness:\n",
            f"  Total nudges: {stats['total_nudges']}",
            f"  Effective: {stats['effective_count']} ({rate:.0f}%)",
            f"  No action: {stats['ineffective_count']}",
            f"  Pending: {stats['pending_count']}",
            f"  Avg time to action: {stats['avg_hours_to_action']:.1f}h",
            f"  Reply rate: {reply_rate:.0f}%",
        ]

        by_type = stats.get("by_type", {})
        if by_type:
            lines.append("\nBy type:")
            for ntype, data in by_type.items():
                type_rate = data["rate"] * 100
                lines.append(f"  {ntype}: {data['effective']}/{data['total']} ({type_rate:.0f}%)")

        return "\n".join(lines)


async def run_daemon(settings: SparkSettings) -> None:
    """Entry point for running the daemon."""
    daemon = SparkDaemon(settings)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(daemon.stop()))

    await daemon.start()
