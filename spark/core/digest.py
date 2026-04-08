"""Daily and weekly digests - project summaries delivered on schedule.

Instead of only reaching out when things stall, Spark can also send
a morning digest summarizing where all projects stand, what has momentum,
and what might need attention. Like a co-founder's daily standup in a text.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import anthropic

from spark.core.context_engine import build_cross_project_context
from spark.core.feedback import get_effectiveness_stats
from spark.core.memory import get_memory_context
from spark.core.prompts.system import SYSTEM_PROMPT
from spark.db.connection import get_session
from spark.db.models import (
    ActivityEvent,
    DigestRecord,
    EventType,
    Message,
    MessageDirection,
    MessageType,
)

logger = logging.getLogger(__name__)

DAILY_DIGEST_PROMPT = """\
Generate a brief daily standup message for your co-founder. \
This is a morning check-in covering all their projects.

PROJECT STATUS:
{project_summaries}

ACTIVITY IN LAST 24 HOURS:
{recent_activity}

{memory_context}

{effectiveness_context}

Write a short, conversational standup message (think co-founder texting you \
in the morning). Cover:
- What's moving (projects with recent activity)
- What might need attention (stalled projects)
- One suggestion or idea for the day

Keep it under 600 characters. Don't list every project - focus on what matters. \
Be specific about files, branches, or commits when relevant. \
Start with a casual opener like "Morning." or "Here's where things are." \
Never use bullet points or headers - this is a text message.\
"""

WEEKLY_DIGEST_PROMPT = """\
Generate a weekly retrospective for your co-founder. \
This is a Friday/Sunday check-in summarizing the week.

PROJECT STATUS:
{project_summaries}

ACTIVITY THIS WEEK:
{weekly_activity}

{memory_context}

NUDGE EFFECTIVENESS:
{effectiveness_context}

Write a short weekly recap (think co-founder reflecting on the week). Cover:
- Wins (what got done)
- Momentum trends (what's accelerating, what's slowing)
- One strategic suggestion for next week

Keep it under 800 characters. Be specific. \
This is a text conversation, not a report.\
"""


def _format_project_summaries(projects: list[dict]) -> str:
    """Format cross-project summaries for the digest prompt."""
    if not projects:
        return "No projects being tracked."

    lines = []
    for p in projects:
        hours = p.get("hours_since_activity")
        time_str = f"{hours:.0f}h ago" if hours else "no activity"
        status = p.get("status", "unknown")
        line = f"- {p['name']} [{status}] last activity: {time_str}"
        if p.get("current_goal"):
            line += f"\n  Goal: {p['current_goal']}"
        lines.append(line)
    return "\n".join(lines)


def _get_recent_activity(hours: int = 24) -> str:
    """Get a summary of activity events in the last N hours."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    with get_session() as session:
        events = (
            session.query(ActivityEvent)
            .filter(ActivityEvent.occurred_at >= cutoff)
            .order_by(ActivityEvent.occurred_at.desc())
            .limit(20)
            .all()
        )

        if not events:
            return "No activity recorded."

        lines = []
        for e in events:
            data = e.event_data or {}
            if e.event_type == EventType.COMMIT.value:
                msg = data.get("message", "?")[:60]
                lines.append(f"- Commit: {msg}")
            elif e.event_type == EventType.FILE_CHANGE.value:
                lines.append(f"- File {data.get('action', 'changed')}: {data.get('file', '?')}")

        return "\n".join(lines) or "No notable activity."


def _already_sent_today(digest_type: str) -> bool:
    """Check if a digest of this type was already sent today."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    with get_session() as session:
        existing = (
            session.query(DigestRecord)
            .filter(
                DigestRecord.digest_type == digest_type,
                DigestRecord.created_at >= today_start,
            )
            .first()
        )
        return existing is not None


def generate_daily_digest(
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
) -> str | None:
    """Generate a daily digest message.

    Returns the digest text, or None if generation fails or
    a digest was already sent today.
    """
    if _already_sent_today("daily"):
        logger.debug("Daily digest already sent today")
        return None

    projects = build_cross_project_context()
    if not projects:
        return None

    project_summaries = _format_project_summaries(projects)
    recent_activity = _get_recent_activity(hours=24)
    memory_context = get_memory_context(max_items=5)
    effectiveness = get_effectiveness_stats()

    eff_context = ""
    if effectiveness["total_nudges"] >= 3:
        rate = effectiveness["effectiveness_rate"] * 100
        eff_context = f"Nudge effectiveness: {rate:.0f}% lead to resumed work"

    prompt = DAILY_DIGEST_PROMPT.format(
        project_summaries=project_summaries,
        recent_activity=recent_activity,
        memory_context=memory_context,
        effectiveness_context=eff_context,
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        digest_text = response.content[0].text.strip()

        # Record the digest and message
        now = datetime.utcnow()
        with get_session() as session:
            msg = Message(
                direction=MessageDirection.OUTBOUND.value,
                content=digest_text,
                message_type=MessageType.DIGEST.value,
                sent_at=now,
            )
            session.add(msg)
            session.flush()

            record = DigestRecord(
                digest_type="daily",
                message_id=msg.id,
                period_start=now - timedelta(hours=24),
                period_end=now,
                project_count=len(projects),
                summary=digest_text[:200],
            )
            session.add(record)

        logger.info("Generated daily digest")
        return digest_text

    except Exception as e:
        logger.error(f"Failed to generate daily digest: {e}")
        return None


def generate_weekly_digest(
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
) -> str | None:
    """Generate a weekly retrospective digest.

    Returns the digest text, or None if generation fails or
    a weekly digest was already sent today.
    """
    if _already_sent_today("weekly"):
        logger.debug("Weekly digest already sent today")
        return None

    projects = build_cross_project_context()
    if not projects:
        return None

    project_summaries = _format_project_summaries(projects)
    weekly_activity = _get_recent_activity(hours=168)  # 7 days
    memory_context = get_memory_context(max_items=5)
    effectiveness = get_effectiveness_stats()

    eff_context = ""
    if effectiveness["total_nudges"] >= 3:
        rate = effectiveness["effectiveness_rate"] * 100
        avg_h = effectiveness["avg_hours_to_action"]
        eff_context = (
            f"This week's nudge effectiveness: {rate:.0f}% led to resumed work, "
            f"avg {avg_h:.1f}h to action"
        )

    prompt = WEEKLY_DIGEST_PROMPT.format(
        project_summaries=project_summaries,
        weekly_activity=weekly_activity,
        memory_context=memory_context,
        effectiveness_context=eff_context,
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        digest_text = response.content[0].text.strip()

        now = datetime.utcnow()
        with get_session() as session:
            msg = Message(
                direction=MessageDirection.OUTBOUND.value,
                content=digest_text,
                message_type=MessageType.DIGEST.value,
                sent_at=now,
            )
            session.add(msg)
            session.flush()

            record = DigestRecord(
                digest_type="weekly",
                message_id=msg.id,
                period_start=now - timedelta(days=7),
                period_end=now,
                project_count=len(projects),
                summary=digest_text[:200],
            )
            session.add(record)

        logger.info("Generated weekly digest")
        return digest_text

    except Exception as e:
        logger.error(f"Failed to generate weekly digest: {e}")
        return None
