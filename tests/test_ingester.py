"""Tests for the knowledge ingester."""

import json
from pathlib import Path

import pytest

from spark.db.connection import get_session, init_db
from spark.db.models import KnowledgeItem, SourceType
from spark.knowledge.ingester import (
    _extract_url_from_file,
    _parse_bookmarks_html,
    ingest_file,
    scan_knowledge_folder,
)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path


@pytest.fixture
def knowledge_dir(tmp_path):
    d = tmp_path / "knowledge"
    d.mkdir()
    return d


class TestIngestFile:
    def test_ingests_markdown_file(self, knowledge_dir):
        md = knowledge_dir / "notes.md"
        md.write_text("# My Notes\n\nSome thoughts about authentication.\n")

        items = ingest_file(md)
        assert len(items) >= 1
        assert items[0].title == "My Notes"
        assert items[0].source_type == SourceType.NOTE.value

    def test_ingests_text_file(self, knowledge_dir):
        txt = knowledge_dir / "ideas.txt"
        txt.write_text("Build a CLI tool for project tracking\n")

        items = ingest_file(txt)
        assert len(items) >= 1
        assert items[0].source_type == SourceType.NOTE.value

    def test_extracts_urls_from_notes(self, knowledge_dir):
        md = knowledge_dir / "links.md"
        md.write_text("Check out https://example.com/cool-lib for auth\n")

        items = ingest_file(md)
        # Should get the note + the extracted URL
        assert len(items) == 2
        urls = [i.source_url for i in items if i.source_url]
        assert "https://example.com/cool-lib" in urls

    def test_ingests_url_shortcut(self, knowledge_dir):
        url_file = knowledge_dir / "reference.url"
        url_file.write_text("[InternetShortcut]\nURL=https://docs.python.org\n")

        items = ingest_file(url_file)
        assert len(items) == 1
        assert items[0].source_url == "https://docs.python.org"
        assert items[0].source_type == SourceType.BOOKMARK.value

    def test_skips_unsupported_files(self, knowledge_dir):
        img = knowledge_dir / "photo.png"
        img.write_bytes(b"\x89PNG\r\n")

        items = ingest_file(img)
        assert len(items) == 0

    def test_handles_nonexistent_file(self, knowledge_dir):
        items = ingest_file(knowledge_dir / "nope.md")
        assert items == []


class TestParseBookmarksHtml:
    def test_parses_netscape_format(self, tmp_path):
        html = tmp_path / "bookmarks.html"
        html.write_text(
            '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n'
            "<DL><DT>"
            '<A HREF="https://example.com" ADD_DATE="1234">Example</A>'
            '<A HREF="https://docs.python.org" ADD_DATE="5678">Python Docs</A>'
            "</DL>"
        )
        bookmarks = _parse_bookmarks_html(html)
        assert len(bookmarks) == 2
        assert bookmarks[0]["url"] == "https://example.com"
        assert bookmarks[0]["title"] == "Example"


class TestExtractUrl:
    def test_windows_url_file(self, tmp_path):
        f = tmp_path / "test.url"
        f.write_text("[InternetShortcut]\nURL=https://example.com\n")
        assert _extract_url_from_file(f) == "https://example.com"

    def test_macos_webloc(self, tmp_path):
        f = tmp_path / "test.webloc"
        f.write_text(
            '<?xml version="1.0"?>'
            "<plist><dict><key>URL</key>"
            "<string>https://example.com</string>"
            "</dict></plist>"
        )
        assert _extract_url_from_file(f) == "https://example.com"


class TestScanKnowledgeFolder:
    def test_scans_and_deduplicates(self, db, knowledge_dir):
        (knowledge_dir / "note1.md").write_text("# First note\n")
        (knowledge_dir / "note2.md").write_text("# Second note\n")

        items1 = scan_knowledge_folder(knowledge_dir)
        items2 = scan_knowledge_folder(knowledge_dir)

        assert len(items1) == 2
        assert len(items2) == 0  # Already ingested

    def test_handles_empty_folder(self, db, knowledge_dir):
        items = scan_knowledge_folder(knowledge_dir)
        assert items == []

    def test_handles_missing_folder(self, db, tmp_path):
        items = scan_knowledge_folder(tmp_path / "nonexistent")
        assert items == []

    def test_ingests_json_bookmarks(self, db, knowledge_dir):
        bookmarks = knowledge_dir / "bookmarks.json"
        bookmarks.write_text(json.dumps([
            {"url": "https://example.com", "title": "Example"},
            {"url": "https://docs.python.org", "title": "Python"},
        ]))

        items = scan_knowledge_folder(knowledge_dir)
        assert len(items) == 2

        with get_session() as session:
            all_items = session.query(KnowledgeItem).all()
            urls = [i.source_url for i in all_items]
            assert "https://example.com" in urls
            assert "https://docs.python.org" in urls
