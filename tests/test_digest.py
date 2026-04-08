"""Tests for the digest system."""

from datetime import datetime, timedelta

import pytest

from spark.db.connection import get_session, init_db
from spark.db.models import (
    ActivityEvent,
    DigestRecord,
    EventType,
    Project,
    ProjectStatus,
)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path


@pytest.fixture
def projects(db):
    """Create some sample projects with activity."""
    with get_session() as session:
        p1 = Project(
            name="webapp",
            local_path="/tmp/webapp",
            description="A web application",
            current_goal="Add user dashboard",
            status=ProjectStatus.ACTIVE.value,
            last_activity_at=datetime.utcnow() - timedelta(hours=2),
        )
        p2 = Project(
            name="api-server",
            local_path="/tmp/api-server",
            description="REST API backend",
            current_goal="Implement auth",
            status=ProjectStatus.ACTIVE.value,
            last_activity_at=datetime.utcnow() - timedelta(hours=48),
        )
        session.add(p1)
        session.add(p2)
        session.flush()
        p1_id = p1.id
        p2_id = p2.id

        # Add some activity events
        event = ActivityEvent(
            project_id=p1_id,
            event_type=EventType.COMMIT.value,
            event_data={"message": "Add dashboard component"},
            occurred_at=datetime.utcnow() - timedelta(hours=2),
        )
        session.add(event)

    return p1_id, p2_id


class TestFormatProjectSummaries:
    def test_formats_projects(self, projects):
        from spark.core.digest import _format_project_summaries
        from spark.core.context_engine import build_cross_project_context

        summaries = build_cross_project_context()
        result = _format_project_summaries(summaries)
        assert "webapp" in result
        assert "api-server" in result
        assert "Add user dashboard" in result

    def test_empty_projects(self, db):
        from spark.core.digest import _format_project_summaries

        result = _format_project_summaries([])
        assert "No projects" in result


class TestGetRecentActivity:
    def test_gets_activity(self, projects):
        from spark.core.digest import _get_recent_activity

        result = _get_recent_activity(hours=24)
        assert "dashboard" in result.lower()

    def test_no_activity(self, db):
        from spark.core.digest import _get_recent_activity

        result = _get_recent_activity(hours=24)
        assert "No activity" in result


class TestAlreadySentToday:
    def test_false_when_no_records(self, db):
        from spark.core.digest import _already_sent_today

        assert _already_sent_today("daily") is False

    def test_true_when_sent_today(self, db):
        from spark.core.digest import _already_sent_today

        with get_session() as session:
            record = DigestRecord(
                digest_type="daily",
                period_start=datetime.utcnow() - timedelta(hours=24),
                period_end=datetime.utcnow(),
                project_count=2,
            )
            session.add(record)

        assert _already_sent_today("daily") is True

    def test_different_types_independent(self, db):
        from spark.core.digest import _already_sent_today

        with get_session() as session:
            record = DigestRecord(
                digest_type="daily",
                period_start=datetime.utcnow() - timedelta(hours=24),
                period_end=datetime.utcnow(),
                project_count=2,
            )
            session.add(record)

        assert _already_sent_today("daily") is True
        assert _already_sent_today("weekly") is False
