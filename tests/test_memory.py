"""Tests for the memory system."""

from datetime import datetime

import pytest

from spark.db.connection import get_session, init_db
from spark.db.models import AgentMemory, MemoryType


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path


class TestStoreMemories:
    def test_stores_valid_memories(self, db):
        from spark.core.memory import store_memories

        memories = [
            {"type": "preference", "content": "Prefers short messages"},
            {"type": "feedback", "content": "Liked the auth suggestion"},
        ]
        stored = store_memories(memories)
        assert stored == 2

        with get_session() as session:
            all_mems = session.query(AgentMemory).all()
            assert len(all_mems) == 2
            types = {m.memory_type for m in all_mems}
            assert "preference" in types
            assert "feedback" in types

    def test_deduplicates_memories(self, db):
        from spark.core.memory import store_memories

        memories = [{"type": "preference", "content": "Likes morning work"}]
        store_memories(memories)
        # Store the same memory again
        stored = store_memories(memories)
        assert stored == 0

        with get_session() as session:
            assert session.query(AgentMemory).count() == 1

    def test_skips_empty_content(self, db):
        from spark.core.memory import store_memories

        memories = [
            {"type": "preference", "content": ""},
            {"type": "preference", "content": "  "},
        ]
        stored = store_memories(memories)
        assert stored == 0

    def test_handles_invalid_memory_type(self, db):
        from spark.core.memory import store_memories

        memories = [{"type": "unknown_type", "content": "Some content"}]
        stored = store_memories(memories)
        assert stored == 1
        # Should default to preference
        with get_session() as session:
            mem = session.query(AgentMemory).first()
            assert mem.memory_type == MemoryType.PREFERENCE.value

    def test_stores_with_source_message_id(self, db):
        from spark.core.memory import store_memories

        memories = [{"type": "goal", "content": "Ship by Friday"}]
        store_memories(memories, source_message_id="msg-123")

        with get_session() as session:
            mem = session.query(AgentMemory).first()
            assert mem.source_message_id == "msg-123"

    def test_empty_list_returns_zero(self, db):
        from spark.core.memory import store_memories

        assert store_memories([]) == 0


class TestRecallMemories:
    def test_recalls_all_memories(self, db):
        from spark.core.memory import recall_memories, store_memories

        store_memories([
            {"type": "preference", "content": "Morning person"},
            {"type": "feedback", "content": "Helpful nudge"},
            {"type": "goal", "content": "Ship by EOW"},
        ])
        result = recall_memories()
        assert len(result) == 3
        # Most recent first
        assert all("content" in m and "type" in m for m in result)

    def test_filters_by_type(self, db):
        from spark.core.memory import recall_memories, store_memories

        store_memories([
            {"type": "preference", "content": "Morning person"},
            {"type": "feedback", "content": "Helpful nudge"},
            {"type": "goal", "content": "Ship by EOW"},
        ])
        result = recall_memories(memory_types=["preference"])
        assert len(result) == 1
        assert result[0]["type"] == "preference"

    def test_respects_limit(self, db):
        from spark.core.memory import recall_memories, store_memories

        store_memories([
            {"type": "preference", "content": f"Memory {i}"} for i in range(10)
        ])
        result = recall_memories(limit=3)
        assert len(result) == 3

    def test_empty_db_returns_empty(self, db):
        from spark.core.memory import recall_memories

        assert recall_memories() == []


class TestGetMemoryContext:
    def test_empty_when_no_memories(self, db):
        from spark.core.memory import get_memory_context

        assert get_memory_context() == ""

    def test_formats_memories_for_prompt(self, db):
        from spark.core.memory import get_memory_context, store_memories

        store_memories([
            {"type": "preference", "content": "Likes short messages"},
            {"type": "pattern", "content": "Responds well to code suggestions"},
        ])
        context = get_memory_context()
        assert "WHAT YOU KNOW" in context
        assert "Likes short messages" in context
        assert "Responds well to code suggestions" in context
