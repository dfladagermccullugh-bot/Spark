"""Analyze user's work rhythm to establish baselines for stall detection."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from spark.db.connection import get_session
from spark.db.models import ActivityEvent, EventType, Project

logger = logging.getLogger(__name__)


def compute_rhythm_profile(project_id: str, lookback_days: int = 30) -> dict:
    """Compute a work rhythm profile for a project.

    Returns a dict with:
        avg_commit_gap_hours: average hours between commits
        median_commit_gap_hours: median gap
        active_days_per_week: average active days per week
        typical_hours: list of hours (0-23) when commits typically happen
        day_of_week_activity: {0-6: count} where 0=Monday
        total_commits: total commits in the lookback period
        last_commit_at: timestamp of most recent commit
    """
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)

    with get_session() as session:
        events = (
            session.query(ActivityEvent)
            .filter(
                ActivityEvent.project_id == project_id,
                ActivityEvent.event_type == EventType.COMMIT.value,
                ActivityEvent.occurred_at >= cutoff,
            )
            .order_by(ActivityEvent.occurred_at.asc())
            .all()
        )

        if not events:
            return {
                "avg_commit_gap_hours": 24.0,  # Default: expect daily activity
                "median_commit_gap_hours": 24.0,
                "active_days_per_week": 0,
                "typical_hours": [],
                "day_of_week_activity": {},
                "total_commits": 0,
                "last_commit_at": None,
            }

        timestamps = [e.occurred_at for e in events]

        # Compute gaps between consecutive commits
        gaps_hours = []
        for i in range(1, len(timestamps)):
            gap = (timestamps[i] - timestamps[i - 1]).total_seconds() / 3600
            # Ignore gaps > 7 days (likely vacations, not normal rhythm)
            if gap < 168:
                gaps_hours.append(gap)

        avg_gap = sum(gaps_hours) / len(gaps_hours) if gaps_hours else 24.0
        sorted_gaps = sorted(gaps_hours)
        median_gap = sorted_gaps[len(sorted_gaps) // 2] if sorted_gaps else 24.0

        # Day-of-week activity
        dow_counts: dict[int, int] = defaultdict(int)
        for ts in timestamps:
            dow_counts[ts.weekday()] += 1

        # Typical hours
        hour_counts: dict[int, int] = defaultdict(int)
        for ts in timestamps:
            hour_counts[ts.hour] += 1
        # Top hours (where > 10% of activity happens)
        total = len(timestamps)
        typical_hours = sorted(
            h for h, c in hour_counts.items() if c / total > 0.1
        )

        # Active days per week
        active_dates = {ts.date() for ts in timestamps}
        weeks = max(lookback_days / 7, 1)
        active_days_per_week = len(active_dates) / weeks

        return {
            "avg_commit_gap_hours": round(avg_gap, 1),
            "median_commit_gap_hours": round(median_gap, 1),
            "active_days_per_week": round(active_days_per_week, 1),
            "typical_hours": typical_hours,
            "day_of_week_activity": dict(dow_counts),
            "total_commits": len(events),
            "last_commit_at": timestamps[-1].isoformat() if timestamps else None,
        }


def update_project_baselines(project_id: str) -> dict:
    """Recompute and store the rhythm profile for a project."""
    profile = compute_rhythm_profile(project_id)

    with get_session() as session:
        project = session.query(Project).filter(Project.id == project_id).first()
        if project:
            project.activity_baseline = profile
            logger.info(f"Updated rhythm for {project.name}: {profile['avg_commit_gap_hours']}h avg gap")

    return profile
