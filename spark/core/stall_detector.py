"""Detect when a project has stalled based on activity rhythm."""

from __future__ import annotations

import logging
import random
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from spark.db.connection import get_session
from spark.db.models import Message, MessageDirection, Project, ProjectStatus, SlowdownDetection

logger = logging.getLogger(__name__)


class StallResult:
    """Result of checking a project for stall."""

    def __init__(
        self,
        project_id: str,
        project_name: str,
        is_stalled: bool,
        confidence: float,
        hours_since_activity: float,
        baseline_gap: float,
        reason: str,
    ):
        self.project_id = project_id
        self.project_name = project_name
        self.is_stalled = is_stalled
        self.confidence = confidence
        self.hours_since_activity = hours_since_activity
        self.baseline_gap = baseline_gap
        self.reason = reason


def _is_quiet_hours(tz_name: str, start_str: str, end_str: str) -> bool:
    """Check if current time is within quiet hours."""
    try:
        tz = ZoneInfo(tz_name)
    except KeyError:
        tz = ZoneInfo("UTC")

    now = datetime.now(tz).time()
    start = time(*map(int, start_str.split(":")))
    end = time(*map(int, end_str.split(":")))

    if start <= end:
        return start <= now <= end
    else:
        # Wraps midnight (e.g., 22:00 - 08:00)
        return now >= start or now <= end


def _recently_nudged(project_id: str, min_hours: float) -> bool:
    """Check if we've already sent a nudge for this project recently."""
    cutoff = datetime.utcnow() - timedelta(hours=min_hours)
    with get_session() as session:
        recent = (
            session.query(Message)
            .filter(
                Message.project_id == project_id,
                Message.direction == MessageDirection.OUTBOUND.value,
                Message.sent_at >= cutoff,
            )
            .first()
        )
        return recent is not None


def _daily_nudge_count() -> int:
    """Count nudges sent today."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    with get_session() as session:
        count = (
            session.query(Message)
            .filter(
                Message.direction == MessageDirection.OUTBOUND.value,
                Message.sent_at >= today_start,
            )
            .count()
        )
        return count


def check_project_stall(
    project_id: str,
    stall_multiplier: float = 2.0,
) -> StallResult:
    """Check if a single project has stalled.

    A project is stalled when the time since last activity exceeds
    the user's baseline commit gap multiplied by stall_multiplier.
    """
    with get_session() as session:
        project = session.query(Project).filter(Project.id == project_id).first()

        if not project or project.status != ProjectStatus.ACTIVE.value:
            return StallResult(
                project_id=project_id,
                project_name=project.name if project else "unknown",
                is_stalled=False,
                confidence=0.0,
                hours_since_activity=0.0,
                baseline_gap=0.0,
                reason="Project not active",
            )

        baseline = project.activity_baseline or {}
        avg_gap = baseline.get("avg_commit_gap_hours", 24.0)
        threshold = avg_gap * stall_multiplier

        if project.last_activity_at is None:
            hours_since = 999.0
        else:
            hours_since = (datetime.utcnow() - project.last_activity_at).total_seconds() / 3600

        is_stalled = hours_since > threshold

        # Confidence scales with how far past the threshold we are
        if is_stalled and threshold > 0:
            overshoot = (hours_since - threshold) / threshold
            confidence = min(0.5 + overshoot * 0.25, 1.0)
        else:
            confidence = 0.0

        reason = (
            f"{hours_since:.1f}h since last activity vs {threshold:.1f}h threshold "
            f"({avg_gap:.1f}h avg * {stall_multiplier}x)"
        )

        return StallResult(
            project_id=project_id,
            project_name=project.name,
            is_stalled=is_stalled,
            confidence=confidence,
            hours_since_activity=hours_since,
            baseline_gap=avg_gap,
            reason=reason,
        )


def detect_stalls(
    timezone: str = "UTC",
    quiet_start: str = "22:00",
    quiet_end: str = "08:00",
    min_hours_between_nudges: float = 4.0,
    max_daily_nudges: int = 3,
    stall_multiplier: float = 2.0,
) -> list[StallResult]:
    """Check all active projects for stalls, respecting quiet hours and rate limits.

    Returns a list of StallResults for projects that need attention.
    """
    # Respect quiet hours
    if _is_quiet_hours(timezone, quiet_start, quiet_end):
        logger.debug("In quiet hours, skipping stall check")
        return []

    # Respect daily limit
    if _daily_nudge_count() >= max_daily_nudges:
        logger.debug(f"Daily nudge limit ({max_daily_nudges}) reached")
        return []

    stalled = []

    with get_session() as session:
        active_projects = (
            session.query(Project)
            .filter(Project.status == ProjectStatus.ACTIVE.value)
            .all()
        )
        project_ids = [(p.id, p.name) for p in active_projects]

    for pid, pname in project_ids:
        # Don't re-nudge too soon
        if _recently_nudged(pid, min_hours_between_nudges):
            logger.debug(f"Recently nudged {pname}, skipping")
            continue

        result = check_project_stall(pid, stall_multiplier)
        if result.is_stalled:
            stalled.append(result)
            logger.info(f"Stall detected: {pname} - {result.reason}")

            # Record the detection
            with get_session() as session:
                detection = SlowdownDetection(
                    project_id=pid,
                    hours_since_last_activity=result.hours_since_activity,
                    baseline_gap_hours=result.baseline_gap,
                    confidence=result.confidence,
                )
                session.add(detection)

    # Sort by confidence (most stalled first) and add jitter so we don't
    # always pick the same project
    stalled.sort(key=lambda r: r.confidence + random.uniform(0, 0.1), reverse=True)
    return stalled
