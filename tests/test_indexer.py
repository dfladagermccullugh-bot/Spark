"""Tests for the ChromaDB indexer."""

import pytest

from spark.db.connection import get_session, init_db
from spark.db.models import KnowledgeItem, SourceType
from spark.knowledge.indexer import (
    index_knowledge_items,
    init_chromadb,
    search_knowledge,
)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path


@pytest.fixture
def chromadb(tmp_path):
    chromadb_path = tmp_path / "chromadb"
    init_chromadb(chromadb_path)
    yield chromadb_path


@pytest.fixture
def sample_knowledge(db):
    """Create some knowledge items in the database."""
    with get_session() as session:
        items = [
            KnowledgeItem(
                source_type=SourceType.NOTE.value,
                title="Authentication best practices",
                content_summary="Use httpOnly cookies instead of localStorage for tokens. Implement CSRF protection with double-submit cookies.",
                tags=["auth", "security"],
            ),
            KnowledgeItem(
                source_type=SourceType.BOOKMARK.value,
                source_url="https://example.com/react-hooks",
                title="React hooks deep dive",
                content_summary="A comprehensive guide to React hooks including useState, useEffect, and custom hooks.",
                tags=["react", "frontend"],
            ),
            KnowledgeItem(
                source_type=SourceType.YOUTUBE.value,
                source_url="https://youtube.com/watch?v=abc123",
                title="Building REST APIs with FastAPI",
                content_summary="Tutorial on building high-performance REST APIs using Python FastAPI framework.",
                tags=["python", "api"],
            ),
        ]
        for item in items:
            session.add(item)


class TestIndexKnowledgeItems:
    def test_indexes_unindexed_items(self, db, chromadb, sample_knowledge):
        count = index_knowledge_items()
        assert count == 3

        # Verify items now have embedding_ids
        with get_session() as session:
            items = session.query(KnowledgeItem).all()
            for item in items:
                assert item.embedding_id is not None

    def test_skips_already_indexed(self, db, chromadb, sample_knowledge):
        count1 = index_knowledge_items()
        count2 = index_knowledge_items()
        assert count1 == 3
        assert count2 == 0

    def test_handles_empty_database(self, db, chromadb):
        count = index_knowledge_items()
        assert count == 0


class TestSearchKnowledge:
    def test_finds_relevant_items(self, db, chromadb, sample_knowledge):
        index_knowledge_items()

        results = search_knowledge("authentication tokens cookies")
        assert len(results) > 0
        # The auth item should be most relevant
        titles = [r["title"] for r in results]
        assert "Authentication best practices" in titles

    def test_returns_empty_for_no_matches(self, db, chromadb):
        results = search_knowledge("completely unrelated query xyz123")
        assert results == []

    def test_respects_n_results(self, db, chromadb, sample_knowledge):
        index_knowledge_items()

        results = search_knowledge("programming", n_results=2)
        assert len(results) <= 2
