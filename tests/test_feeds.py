"""Tests for external feed connectors."""

import json
from pathlib import Path

import pytest

from spark.db.connection import get_session, init_db
from spark.db.models import KnowledgeItem, SourceType
from spark.knowledge.feeds import (
    auto_detect_and_import,
    import_chrome_bookmarks,
    import_twitter_bookmarks,
    import_youtube_takeout,
)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path


class TestChromeBookmarks:
    def test_imports_chrome_format(self, db, tmp_path):
        bookmarks = {
            "roots": {
                "bookmark_bar": {
                    "type": "folder",
                    "name": "Bookmarks Bar",
                    "children": [
                        {
                            "type": "url",
                            "name": "Python Docs",
                            "url": "https://docs.python.org",
                        },
                        {
                            "type": "url",
                            "name": "GitHub",
                            "url": "https://github.com",
                        },
                        {
                            "type": "folder",
                            "name": "Dev",
                            "children": [
                                {
                                    "type": "url",
                                    "name": "FastAPI",
                                    "url": "https://fastapi.tiangolo.com",
                                },
                            ],
                        },
                    ],
                }
            }
        }
        path = tmp_path / "Bookmarks"
        path.write_text(json.dumps(bookmarks))

        count = import_chrome_bookmarks(path)
        assert count == 3

        with get_session() as session:
            items = session.query(KnowledgeItem).all()
            urls = {i.source_url for i in items}
            assert "https://docs.python.org" in urls
            assert "https://github.com" in urls
            assert "https://fastapi.tiangolo.com" in urls

    def test_deduplicates_on_reimport(self, db, tmp_path):
        bookmarks = {
            "roots": {
                "bookmark_bar": {
                    "type": "folder",
                    "name": "Bar",
                    "children": [
                        {"type": "url", "name": "Test", "url": "https://example.com"},
                    ],
                }
            }
        }
        path = tmp_path / "Bookmarks"
        path.write_text(json.dumps(bookmarks))

        count1 = import_chrome_bookmarks(path)
        count2 = import_chrome_bookmarks(path)
        assert count1 == 1
        assert count2 == 0


class TestYouTubeTakeout:
    def test_imports_csv(self, db, tmp_path):
        csv_content = "Video Id,Title\nabc123,Cool Tutorial\ndef456,Python Tips\n"
        path = tmp_path / "liked-videos.csv"
        path.write_text(csv_content)

        count = import_youtube_takeout(path)
        assert count == 2

        with get_session() as session:
            items = session.query(KnowledgeItem).all()
            assert all(i.source_type == SourceType.YOUTUBE.value for i in items)
            urls = {i.source_url for i in items}
            assert "https://www.youtube.com/watch?v=abc123" in urls

    def test_imports_json(self, db, tmp_path):
        data = [
            {"title": "Video One", "titleUrl": "https://www.youtube.com/watch?v=vid1"},
            {"title": "Video Two", "titleUrl": "https://www.youtube.com/watch?v=vid2"},
        ]
        path = tmp_path / "watch-history.json"
        path.write_text(json.dumps(data))

        count = import_youtube_takeout(path)
        assert count == 2

    def test_imports_html(self, db, tmp_path):
        html = (
            '<html><body>'
            '<a href="https://www.youtube.com/watch?v=xyz">Great Video</a>'
            '<a href="https://www.youtube.com/watch?v=abc">Another One</a>'
            '</body></html>'
        )
        path = tmp_path / "history.html"
        path.write_text(html)

        count = import_youtube_takeout(path)
        assert count == 2


class TestTwitterBookmarks:
    def test_imports_twitter_export(self, db, tmp_path):
        data = [
            {
                "tweet": {
                    "id": "123456",
                    "full_text": "Great thread on microservices architecture",
                }
            },
            {
                "tweet": {
                    "id": "789012",
                    "full_text": "Check out this new Python library https://t.co/abc",
                    "entities": {
                        "urls": [
                            {"expanded_url": "https://example.com/cool-lib"}
                        ]
                    },
                }
            },
        ]
        path = tmp_path / "bookmarks.js"
        path.write_text(f"window.YTD.bookmarks.part0 = {json.dumps(data)}")

        count = import_twitter_bookmarks(path)
        assert count == 2

        with get_session() as session:
            items = session.query(KnowledgeItem).all()
            assert all(i.source_type == SourceType.TWITTER.value for i in items)

    def test_imports_plain_json(self, db, tmp_path):
        data = [
            {"id": "111", "text": "Interesting tweet about databases"},
        ]
        path = tmp_path / "tweets.json"
        path.write_text(json.dumps(data))

        count = import_twitter_bookmarks(path)
        assert count == 1


class TestAutoDetect:
    def test_detects_chrome_bookmarks(self, db, tmp_path):
        data = {
            "roots": {
                "bookmark_bar": {
                    "type": "folder",
                    "name": "Bar",
                    "children": [
                        {"type": "url", "name": "Test", "url": "https://example.com"},
                    ],
                }
            }
        }
        path = tmp_path / "bookmarks.json"
        path.write_text(json.dumps(data))

        count = auto_detect_and_import(path)
        assert count == 1

    def test_detects_youtube(self, db, tmp_path):
        data = [{"title": "Video", "titleUrl": "https://youtube.com/watch?v=x"}]
        path = tmp_path / "youtube-history.json"
        path.write_text(json.dumps(data))

        count = auto_detect_and_import(path)
        assert count == 1

    def test_returns_zero_for_unknown(self, db, tmp_path):
        path = tmp_path / "random.txt"
        path.write_text("just some text")
        count = auto_detect_and_import(path)
        assert count == 0
