"""Tests for the content enricher."""

import pytest

from spark.db.connection import get_session, init_db
from spark.db.models import KnowledgeItem, SourceType


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path


class TestShouldSkipUrl:
    def test_skips_social_media(self):
        from spark.knowledge.enricher import _should_skip_url

        assert _should_skip_url("https://twitter.com/user/status/123") is True
        assert _should_skip_url("https://x.com/user/status/123") is True
        assert _should_skip_url("https://facebook.com/post/123") is True
        assert _should_skip_url("https://www.instagram.com/p/123") is True

    def test_allows_tech_sites(self):
        from spark.knowledge.enricher import _should_skip_url

        assert _should_skip_url("https://blog.example.com/post") is False
        assert _should_skip_url("https://docs.python.org/3/") is False
        assert _should_skip_url("https://stackoverflow.com/q/123") is False

    def test_skips_empty_urls(self):
        from spark.knowledge.enricher import _should_skip_url

        assert _should_skip_url("") is True
        assert _should_skip_url(None) is True


class TestTextExtractor:
    def test_extracts_text_from_html(self):
        from spark.knowledge.enricher import _extract_text_from_html

        html = """
        <html>
        <head><title>Test</title></head>
        <body>
            <nav>Navigation stuff</nav>
            <main>
                <h1>Article Title</h1>
                <p>This is the main content.</p>
                <p>More content here.</p>
            </main>
            <script>var x = 1;</script>
            <footer>Footer stuff</footer>
        </body>
        </html>
        """
        text = _extract_text_from_html(html)
        assert "Article Title" in text
        assert "main content" in text
        # Script content should be excluded
        assert "var x" not in text
        # Nav/footer should be excluded
        assert "Navigation stuff" not in text

    def test_handles_malformed_html(self):
        from spark.knowledge.enricher import _extract_text_from_html

        text = _extract_text_from_html("<p>Unclosed tag <b>bold")
        assert "Unclosed tag" in text

    def test_truncates_long_content(self):
        from spark.knowledge.enricher import _extract_text_from_html, MAX_CONTENT_LENGTH

        long_html = "<p>" + "x" * 20000 + "</p>"
        text = _extract_text_from_html(long_html)
        assert len(text) <= MAX_CONTENT_LENGTH


class TestEnrichKnowledgeItems:
    def test_skips_when_no_candidates(self, db):
        from spark.knowledge.enricher import enrich_knowledge_items

        enriched = enrich_knowledge_items(api_key="test-key", batch_size=5)
        assert enriched == 0

    def test_marks_enriched_with_existing_summary(self, db):
        from spark.knowledge.enricher import enrich_knowledge_items

        with get_session() as session:
            item = KnowledgeItem(
                source_type=SourceType.BOOKMARK.value,
                source_url="https://example.com/article",
                title="Test Article",
                content_summary="A" * 200,  # Already has good summary
            )
            session.add(item)

        # Should mark as enriched without calling API
        enriched = enrich_knowledge_items(api_key="test-key", batch_size=5)
        assert enriched == 0

        with get_session() as session:
            item = session.query(KnowledgeItem).first()
            assert item.enriched_at is not None
