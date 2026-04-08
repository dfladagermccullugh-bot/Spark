"""Tests for the feedback loop."""

from datetime import datetime, timedelta

import pytest

from spark.db.connection import get_session, init_db
from spark.db.models import (
    ActivityEvent,
    EventType,
    Message,
    MessageDirection,
    MessageType,
    NudgeFeedback,
    Project,
    ProjectStatus,
)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path


@pytest.fixture
def project_with_nudge(db):
    """Create a project, message, and nudge feedback record."""
    with get_session() as session:
        project = Project(
            name="test-project",
            local_path="/tmp/test-project",
            status=ProjectStatus.ACTIVE.value,
        )
        session.add(project)
        session.flush()
        pid = project.id

        msg = Message(
            project_id=pid,
            direction=MessageDirection.OUTBOUND.value,
            content="Have you considered using async handlers?",
            message_type=MessageType.NUDGE.value,
            sent_at=datetime.utcnow() - timedelta(hours=3),
        )
        session.add(msg)
        session.flush()
        mid = msg.id

    return pid, mid


class TestRecordNudgeSent:
    def test_creates_feedback_record(self, project_with_nudge):
        from spark.core.feedback import record_nudge_sent

        pid, mid = project_with_nudge
        record_nudge_sent(mid, pid, "nudge")

        with get_session() as session:
            record = session.query(NudgeFeedback).first()
            assert record is not None
            assert record.message_id == mid
            assert record.project_id == pid
            assert record.was_effective is None


class TestCheckNudgeEffectiveness:
    def test_marks_effective_when_activity_follows(self, project_with_nudge):
        from spark.core.feedback import check_nudge_effectiveness, record_nudge_sent

        pid, mid = project_with_nudge

        nudge_time = datetime.utcnow() - timedelta(hours=3)
        record_nudge_sent(mid, pid, "nudge")

        # Update the sent_at to 3 hours ago
        with get_session() as session:
            fb = session.query(NudgeFeedback).first()
            fb.sent_at = nudge_time

        # Add activity 1 hour after nudge
        with get_session() as session:
            event = ActivityEvent(
                project_id=pid,
                event_type=EventType.COMMIT.value,
                event_data={"message": "Fix auth handler"},
                occurred_at=nudge_time + timedelta(hours=1),
            )
            session.add(event)

        updated = check_nudge_effectiveness()
        assert updated == 1

        with get_session() as session:
            fb = session.query(NudgeFeedback).first()
            assert fb.was_effective is True
            assert fb.hours_to_action is not None
            assert fb.hours_to_action < 2.0

    def test_marks_ineffective_after_window_expires(self, project_with_nudge):
        from spark.core.feedback import check_nudge_effectiveness, record_nudge_sent

        pid, mid = project_with_nudge

        record_nudge_sent(mid, pid, "nudge")

        # Set sent_at to 13 hours ago (past the 12h window)
        with get_session() as session:
            fb = session.query(NudgeFeedback).first()
            fb.sent_at = datetime.utcnow() - timedelta(hours=13)

        updated = check_nudge_effectiveness()
        assert updated == 1

        with get_session() as session:
            fb = session.query(NudgeFeedback).first()
            assert fb.was_effective is False

    def test_skips_recently_sent(self, project_with_nudge):
        from spark.core.feedback import check_nudge_effectiveness, record_nudge_sent

        pid, mid = project_with_nudge

        record_nudge_sent(mid, pid, "nudge")
        # Sent just now - too soon to evaluate
        updated = check_nudge_effectiveness()
        assert updated == 0

    def test_detects_user_reply(self, project_with_nudge):
        from spark.core.feedback import check_nudge_effectiveness, record_nudge_sent

        pid, mid = project_with_nudge

        nudge_time = datetime.utcnow() - timedelta(hours=3)
        record_nudge_sent(mid, pid, "nudge")

        with get_session() as session:
            fb = session.query(NudgeFeedback).first()
            fb.sent_at = nudge_time

        # Add a user reply
        with get_session() as session:
            reply = Message(
                project_id=pid,
                direction=MessageDirection.INBOUND.value,
                content="Good idea, let me try that",
                message_type=MessageType.REPLY.value,
                sent_at=nudge_time + timedelta(hours=0.5),
            )
            session.add(reply)

            # Also add a commit
            event = ActivityEvent(
                project_id=pid,
                event_type=EventType.COMMIT.value,
                event_data={"message": "Implement async handlers"},
                occurred_at=nudge_time + timedelta(hours=1),
            )
            session.add(event)

        check_nudge_effectiveness()

        with get_session() as session:
            fb = session.query(NudgeFeedback).first()
            assert fb.user_replied is True
            assert fb.was_effective is True


class TestEffectivenessStats:
    def test_empty_stats(self, db):
        from spark.core.feedback import get_effectiveness_stats

        stats = get_effectiveness_stats()
        assert stats["total_nudges"] == 0
        assert stats["effectiveness_rate"] == 0.0

    def test_computes_stats(self, db):
        from spark.core.feedback import get_effectiveness_stats

        with get_session() as session:
            project = Project(
                name="test", local_path="/tmp/test",
                status=ProjectStatus.ACTIVE.value,
            )
            session.add(project)
            session.flush()
            pid = project.id

            msg = Message(
                project_id=pid,
                direction=MessageDirection.OUTBOUND.value,
                content="test",
                message_type=MessageType.NUDGE.value,
                sent_at=datetime.utcnow(),
            )
            session.add(msg)
            session.flush()
            mid = msg.id

            # 2 effective, 1 not
            for i, effective in enumerate([True, True, False]):
                fb = NudgeFeedback(
                    message_id=mid,
                    project_id=pid,
                    nudge_type="nudge",
                    sent_at=datetime.utcnow() - timedelta(hours=i + 1),
                    was_effective=effective,
                    hours_to_action=2.0 if effective else None,
                )
                session.add(fb)

        stats = get_effectiveness_stats()
        assert stats["total_nudges"] == 3
        assert stats["effective_count"] == 2
        assert stats["ineffective_count"] == 1
        assert stats["effectiveness_rate"] == pytest.approx(0.667, abs=0.01)
        assert stats["avg_hours_to_action"] == 2.0


class TestFeedbackContext:
    def test_empty_when_too_few_nudges(self, db):
        from spark.core.feedback import get_feedback_context

        assert get_feedback_context() == ""

    def test_formats_context(self, db):
        from spark.core.feedback import get_feedback_context

        with get_session() as session:
            project = Project(
                name="test", local_path="/tmp/test",
                status=ProjectStatus.ACTIVE.value,
            )
            session.add(project)
            session.flush()
            pid = project.id

            msg = Message(
                project_id=pid,
                direction=MessageDirection.OUTBOUND.value,
                content="test",
                message_type=MessageType.NUDGE.value,
                sent_at=datetime.utcnow(),
            )
            session.add(msg)
            session.flush()
            mid = msg.id

            for effective in [True, True, True, False]:
                fb = NudgeFeedback(
                    message_id=mid,
                    project_id=pid,
                    nudge_type="nudge",
                    sent_at=datetime.utcnow(),
                    was_effective=effective,
                    hours_to_action=1.5 if effective else None,
                )
                session.add(fb)

        context = get_feedback_context()
        assert "NUDGE EFFECTIVENESS" in context
        assert "75%" in context
