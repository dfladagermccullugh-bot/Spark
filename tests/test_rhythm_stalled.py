"""Baselines must survive a long stall (window anchored to last commit)."""

from datetime import datetime, timedelta

from spark.core.rhythm import compute_rhythm_profile
from spark.db.connection import get_session, init_db
from spark.db.models import ActivityEvent, EventType, Project


def test_baseline_computed_from_last_active_period(tmp_path):
    init_db(tmp_path / "t.db")
    base = datetime.utcnow() - timedelta(days=200)
    with get_session() as s:
        p = Project(name="old", local_path=str(tmp_path))
        s.add(p)
        s.flush()
        pid = p.id
        for i in range(5):
            s.add(ActivityEvent(project_id=pid, event_type=EventType.COMMIT.value,
                                event_data={}, occurred_at=base + timedelta(hours=10 * i)))
    prof = compute_rhythm_profile(pid)
    assert prof["total_commits"] == 5
    assert prof["avg_commit_gap_hours"] == 10.0
