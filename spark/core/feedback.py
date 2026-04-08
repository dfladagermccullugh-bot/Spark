"""Feedback loop - track which nudges actually lead to action.

Implicit feedback: after sending a nudge, monitor whether the user
resumes work on the project. If commits appear within N hours,
the nudge was likely effective. Over time this data tells Spark
which kinds of nudges work best for each user.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from spark.db.connection import get_session
from spark.db.models import (
    ActivityEvent,
    EventType,
    Message,
    MessageDirection,
    MessageType,
    NudgeFeedback,
)

logger = logging.getLogger(__name__)

# How long after a nudge to consider resumed activity as a response
FEEDBACK_WINDOW_HOURS = 12.0

# Minimum gap to consider a nudge effective (not just coincidence)
MIN_GAP_HOURS = 0.5


def record_nudge_sent(message_id: str, project_id: str, nudge_type: str) -> None:
    """Record that a nudge was sent, for later feedback tracking."""
    with get_session() as session:
        feedback = NudgeFeedback(
            message_id=message_id,
            project_id=project_id,
            nudge_type=nudge_type,
            sent_at=datetime.utcnow(),
        )
        session.add(feedback)

    logger.debug(f"Recorded nudge for feedback tracking: {message_id}")


def check_nudge_effectiveness() -> int:
    """Check pending nudge feedback records for resumed activity.

    Looks at nudges that haven't been evaluated yet and checks if
    the user resumed working on the project within the feedback window.

    Returns the number of feedback records updated.
    """
    updated = 0

    with get_session() as session:
        # Find unresolved feedback records (no was_effective set)
        pending = (
            session.query(NudgeFeedback)
            .filter(NudgeFeedback.was_effective.is_(None))
            .all()
        )

        now = datetime.utcnow()

        for feedback in pending:
            age_hours = (now - feedback.sent_at).total_seconds() / 3600

            # Too soon to judge - skip
            if age_hours < MIN_GAP_HOURS:
                continue

            # Check for activity after the nudge was sent
            activity = (
                session.query(ActivityEvent)
                .filter(
                    ActivityEvent.project_id == feedback.project_id,
                    ActivityEvent.event_type == EventType.COMMIT.value,
                    ActivityEvent.occurred_at > feedback.sent_at,
                    ActivityEvent.occurred_at
                    <= feedback.sent_at + timedelta(hours=FEEDBACK_WINDOW_HOURS),
                )
                .order_by(ActivityEvent.occurred_at.asc())
                .first()
            )

            # Check for user reply to the nudge
            reply = (
                session.query(Message)
                .filter(
                    Message.direction == MessageDirection.INBOUND.value,
                    Message.sent_at > feedback.sent_at,
                    Message.sent_at
                    <= feedback.sent_at + timedelta(hours=FEEDBACK_WINDOW_HOURS),
                )
                .first()
            )

            if reply:
                feedback.user_replied = True

            if activity:
                feedback.activity_resumed_at = activity.occurred_at
                feedback.hours_to_action = (
                    (activity.occurred_at - feedback.sent_at).total_seconds() / 3600
                )
                feedback.was_effective = True
                updated += 1
            elif age_hours > FEEDBACK_WINDOW_HOURS:
                # Window expired with no activity - mark as not effective
                feedback.was_effective = False
                updated += 1

    if updated:
        logger.info(f"Updated feedback for {updated} nudges")
    return updated


def get_effectiveness_stats() -> dict:
    """Compute overall nudge effectiveness statistics.

    Returns a dict with:
        total_nudges, effective_count, ineffective_count, pending_count,
        effectiveness_rate, avg_hours_to_action, reply_rate,
        by_type: {nudge_type: {effective, total, rate}}
    """
    with get_session() as session:
        all_feedback = session.query(NudgeFeedback).all()

        if not all_feedback:
            return {
                "total_nudges": 0,
                "effective_count": 0,
                "ineffective_count": 0,
                "pending_count": 0,
                "effectiveness_rate": 0.0,
                "avg_hours_to_action": 0.0,
                "reply_rate": 0.0,
                "by_type": {},
            }

        total = len(all_feedback)
        effective = [f for f in all_feedback if f.was_effective is True]
        ineffective = [f for f in all_feedback if f.was_effective is False]
        pending = [f for f in all_feedback if f.was_effective is None]
        replied = [f for f in all_feedback if f.user_replied]

        hours_to_action = [
            f.hours_to_action for f in effective if f.hours_to_action is not None
        ]
        avg_hours = sum(hours_to_action) / len(hours_to_action) if hours_to_action else 0.0

        evaluated = len(effective) + len(ineffective)
        rate = len(effective) / evaluated if evaluated > 0 else 0.0

        # Break down by nudge type
        by_type: dict[str, dict] = {}
        for f in all_feedback:
            entry = by_type.setdefault(f.nudge_type, {"effective": 0, "total": 0})
            entry["total"] += 1
            if f.was_effective is True:
                entry["effective"] += 1

        for entry in by_type.values():
            entry["rate"] = (
                entry["effective"] / entry["total"] if entry["total"] > 0 else 0.0
            )

        return {
            "total_nudges": total,
            "effective_count": len(effective),
            "ineffective_count": len(ineffective),
            "pending_count": len(pending),
            "effectiveness_rate": round(rate, 3),
            "avg_hours_to_action": round(avg_hours, 1),
            "reply_rate": round(len(replied) / total, 3) if total > 0 else 0.0,
            "by_type": by_type,
        }


def get_feedback_context() -> str:
    """Build a context string about nudge effectiveness for the prompt system.

    Returns a short summary that helps Spark understand what works.
    """
    stats = get_effectiveness_stats()
    if stats["total_nudges"] < 3:
        return ""  # Not enough data to be useful

    lines = ["NUDGE EFFECTIVENESS (what works for your co-founder):"]
    rate_pct = stats["effectiveness_rate"] * 100
    lines.append(
        f"- Overall: {rate_pct:.0f}% of nudges lead to resumed work "
        f"(avg {stats['avg_hours_to_action']:.1f}h to action)"
    )
    lines.append(f"- Reply rate: {stats['reply_rate'] * 100:.0f}%")

    # Highlight best/worst performing nudge types
    by_type = stats["by_type"]
    if by_type:
        best = max(by_type.items(), key=lambda x: x[1]["rate"])
        if best[1]["total"] >= 2:
            lines.append(
                f"- Best performing: {best[0]} nudges ({best[1]['rate'] * 100:.0f}% effective)"
            )

    return "\n".join(lines)
