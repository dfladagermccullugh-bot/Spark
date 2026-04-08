"""SQLAlchemy models for Spark's data store."""

from __future__ import annotations

import uuid
from datetime import datetime, time
from enum import Enum

from sqlalchemy import Boolean, JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    SHIPPED = "shipped"
    ABANDONED = "abandoned"


class EventType(str, Enum):
    COMMIT = "commit"
    FILE_CHANGE = "file_change"
    BRANCH = "branch"
    PR = "pr"


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageType(str, Enum):
    NUDGE = "nudge"
    IDEA = "idea"
    CONNECTION = "connection"
    CONTRIBUTION = "contribution"
    REPLY = "reply"
    DIGEST = "digest"


class MemoryType(str, Enum):
    PREFERENCE = "preference"
    FEEDBACK = "feedback"
    GOAL = "goal"
    RELATIONSHIP = "relationship"
    PATTERN = "pattern"


class TaskType(str, Enum):
    CODE_GEN = "code_gen"
    PR = "pr"
    RESEARCH = "research"
    ISSUE = "issue"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class SourceType(str, Enum):
    FILE = "file"
    BOOKMARK = "bookmark"
    YOUTUBE = "youtube"
    TWITTER = "twitter"
    NOTE = "note"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    local_path: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    github_repo: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default=ProjectStatus.ACTIVE.value)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activity_baseline: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    activity_events: Mapped[list[ActivityEvent]] = relationship(back_populates="project")
    slowdown_detections: Mapped[list[SlowdownDetection]] = relationship(back_populates="project")
    messages: Mapped[list[Message]] = relationship(back_populates="project")


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    event_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    project: Mapped[Project] = relationship(back_populates="activity_events")


class SlowdownDetection(Base):
    __tablename__ = "slowdown_detections"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    hours_since_last_activity: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_gap_hours: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    action_taken: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship(back_populates="slowdown_detections")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(String, nullable=False)
    context_used: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    knowledge_items_referenced: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped[Project | None] = relationship(back_populates="messages")


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    content_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_content_path: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    relevance_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentMemory(Base):
    __tablename__ = "agent_memory"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    memory_type: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default=TaskStatus.PENDING.value)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    triggered_by_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NudgeFeedback(Base):
    """Track whether nudges led to action (implicit feedback loop)."""

    __tablename__ = "nudge_feedback"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    nudge_type: Mapped[str] = mapped_column(String, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    activity_resumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hours_to_action: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_replied: Mapped[bool] = mapped_column(Boolean, default=False)
    was_effective: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    context_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)


class DigestRecord(Base):
    """Track digests sent to avoid duplicates."""

    __tablename__ = "digest_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    digest_type: Mapped[str] = mapped_column(String, nullable=False)  # "daily" or "weekly"
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True
    )
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    project_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
