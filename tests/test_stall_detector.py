"""Tests for stall detection logic."""

from datetime import datetime, timedelta

import pytest

from spark.config import get_settings
from spark.db.connection import get_session, init_db
from spark.db.models import (
    ActivityEvent,
    Base,
    EventType,
    Message,
    MessageDirection,
    MessageType,
    Project,
    ProjectStatus,
)
from spark.core.stall_detector import StallResult, check_project_stall, _recently_nudged, _daily_nudge_count


@pytest.fixture
def db(tmp_path):
    """Set up a temporary database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path


@pytest.fixture
def active_project(db):
    """Create an active project with baseline rhythm."""
    with get_session() as session:
        project = Project(
            name="test-project",
            local_path="/tmp/test-project",
            status=ProjectStatus.ACTIVE.value,
            last_activity_at=datetime.utcnow() - timedelta(hours=10),
            activity_baseline={
                "avg_commit_gap_hours": 4.0,
                "median_commit_gap_hours": 3.5,
            },
        )
        session.add(project)
        session.flush()
        pid = project.id
    return pid


@pytest.fixture
def fresh_project(db):
    """Create a project with very recent activity."""
    with get_session() as session:
        project = Project(
            name="fresh-project",
            local_path="/tmp/fresh-project",
            status=ProjectStatus.ACTIVE.value,
            last_activity_at=datetime.utcnow() - timedelta(minutes=30),
            activity_baseline={
                "avg_commit_gap_hours": 4.0,
            },
        )
        session.add(project)
        session.flush()
        pid = project.id
    return pid


class TestCheckProjectStall:
    def test_detects_stall_when_gap_exceeds_threshold(self, active_project):
        """Project with 10h gap and 4h avg * 2x threshold = 8h -> stalled."""
        result = check_project_stall(active_project, stall_multiplier=2.0)
        assert result.is_stalled is True
        assert result.confidence > 0.0
        assert result.hours_since_activity > 8.0

    def test_no_stall_when_recent_activity(self, fresh_project):
        """Project with 30min gap and 4h avg * 2x threshold = 8h -> not stalled."""
        result = check_project_stall(fresh_project, stall_multiplier=2.0)
        assert result.is_stalled is False
        assert result.confidence == 0.0

    def test_paused_project_never_stalls(self, db):
        """Paused projects should not trigger stalls."""
        with get_session() as session:
            project = Project(
                name="paused-project",
                local_path="/tmp/paused-project",
                status=ProjectStatus.PAUSED.value,
                last_activity_at=datetime.utcnow() - timedelta(days=30),
            )
            session.add(project)
            session.flush()
            pid = project.id

        result = check_project_stall(pid)
        assert result.is_stalled is False

    def test_confidence_increases_with_gap_size(self, db):
        """Confidence should be higher when further past threshold."""
        with get_session() as session:
            # Way past threshold
            p1 = Project(
                name="very-stalled",
                local_path="/tmp/very-stalled",
                status=ProjectStatus.ACTIVE.value,
                last_activity_at=datetime.utcnow() - timedelta(hours=48),
                activity_baseline={"avg_commit_gap_hours": 4.0},
            )
            # Just past threshold
            p2 = Project(
                name="slightly-stalled",
                local_path="/tmp/slightly-stalled",
                status=ProjectStatus.ACTIVE.value,
                last_activity_at=datetime.utcnow() - timedelta(hours=9),
                activity_baseline={"avg_commit_gap_hours": 4.0},
            )
            session.add(p1)
            session.add(p2)
            session.flush()
            pid1, pid2 = p1.id, p2.id

        r1 = check_project_stall(pid1, stall_multiplier=2.0)
        r2 = check_project_stall(pid2, stall_multiplier=2.0)
        assert r1.confidence > r2.confidence

    def test_project_with_no_activity_is_stalled(self, db):
        """Project that has never had activity should be considered stalled."""
        with get_session() as session:
            project = Project(
                name="no-activity",
                local_path="/tmp/no-activity",
                status=ProjectStatus.ACTIVE.value,
                last_activity_at=None,
                activity_baseline={"avg_commit_gap_hours": 4.0},
            )
            session.add(project)
            session.flush()
            pid = project.id

        result = check_project_stall(pid)
        assert result.is_stalled is True


class TestRecentlyNudged:
    def test_no_recent_nudge(self, active_project):
        """Should return False when no nudges exist."""
        assert _recently_nudged(active_project, min_hours=4.0) is False

    def test_recent_nudge_blocks(self, active_project):
        """Should return True when a recent nudge exists."""
        with get_session() as session:
            msg = Message(
                project_id=active_project,
                direction=MessageDirection.OUTBOUND.value,
                content="Test nudge",
                message_type=MessageType.NUDGE.value,
                sent_at=datetime.utcnow() - timedelta(hours=1),
            )
            session.add(msg)

        assert _recently_nudged(active_project, min_hours=4.0) is True

    def test_old_nudge_allows(self, active_project):
        """Should return False when the nudge is old enough."""
        with get_session() as session:
            msg = Message(
                project_id=active_project,
                direction=MessageDirection.OUTBOUND.value,
                content="Old nudge",
                message_type=MessageType.NUDGE.value,
                sent_at=datetime.utcnow() - timedelta(hours=5),
            )
            session.add(msg)

        assert _recently_nudged(active_project, min_hours=4.0) is False


class TestDailyNudgeCount:
    def test_zero_nudges_today(self, db):
        assert _daily_nudge_count() == 0

    def test_counts_todays_nudges(self, db):
        with get_session() as session:
            for i in range(3):
                msg = Message(
                    direction=MessageDirection.OUTBOUND.value,
                    content=f"Nudge {i}",
                    message_type=MessageType.NUDGE.value,
                    sent_at=datetime.utcnow() - timedelta(hours=i),
                )
                session.add(msg)

        assert _daily_nudge_count() == 3
