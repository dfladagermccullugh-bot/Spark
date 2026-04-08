"""Ingest knowledge items from the knowledge folder and external sources.

Handles: text files, markdown, PDFs, URLs in .url/.webloc files,
bookmark exports (HTML), and plain text notes.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from spark.db.connection import get_session
from spark.db.models import KnowledgeItem, SourceType

logger = logging.getLogger(__name__)

# File extensions we know how to ingest
SUPPORTED_EXTENSIONS = {
    ".md", ".txt", ".rst", ".org",  # Text/notes
    ".json",  # Structured data (bookmarks exports, etc.)
    ".html", ".htm",  # Bookmark exports
    ".url", ".webloc",  # URL shortcut files
    ".csv",  # Simple tabular data
}

MAX_CONTENT_LENGTH = 50_000  # Max chars to store per item


class _BookmarkHTMLParser(HTMLParser):
    """Parse Netscape bookmark HTML export format (Chrome, Firefox, etc.)."""

    def __init__(self):
        super().__init__()
        self.bookmarks: list[dict] = []
        self._current_url: str | None = None
        self._current_title: str = ""
        self._in_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attr_dict = dict(attrs)
            self._current_url = attr_dict.get("href")
            self._current_title = ""
            self._in_link = True

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._current_title += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            if self._current_url:
                self.bookmarks.append({
                    "url": self._current_url,
                    "title": self._current_title.strip(),
                })
            self._in_link = False
            self._current_url = None


def _read_text_file(path: Path) -> str | None:
    """Read a text file, returning None on failure."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + "\n... (truncated)"
        return content
    except Exception as e:
        logger.warning(f"Failed to read {path}: {e}")
        return None


def _extract_url_from_file(path: Path) -> str | None:
    """Extract URL from .url or .webloc shortcut files."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        # Windows .url format
        match = re.search(r"URL=(.+)", content)
        if match:
            return match.group(1).strip()
        # macOS .webloc plist format
        match = re.search(r"<string>(https?://[^<]+)</string>", content)
        if match:
            return match.group(1).strip()
    except Exception:
        pass
    return None


def _parse_bookmarks_html(path: Path) -> list[dict]:
    """Parse a Netscape bookmark HTML export file."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        parser = _BookmarkHTMLParser()
        parser.feed(content)
        return parser.bookmarks
    except Exception as e:
        logger.warning(f"Failed to parse bookmarks from {path}: {e}")
        return []


def _parse_json_bookmarks(path: Path) -> list[dict]:
    """Parse JSON bookmark exports (Chrome format, custom exports, etc.)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))

        bookmarks = []

        # Handle flat list of {url, title} objects
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "url" in item:
                    bookmarks.append({
                        "url": item["url"],
                        "title": item.get("title", item.get("name", "")),
                    })
            return bookmarks

        # Handle Chrome's nested bookmark format
        def _walk_chrome(node: dict) -> None:
            if node.get("type") == "url":
                bookmarks.append({
                    "url": node.get("url", ""),
                    "title": node.get("name", ""),
                })
            for child in node.get("children", []):
                _walk_chrome(child)

        if "roots" in data:
            for root in data["roots"].values():
                if isinstance(root, dict):
                    _walk_chrome(root)
            return bookmarks

        return bookmarks
    except Exception as e:
        logger.warning(f"Failed to parse JSON bookmarks from {path}: {e}")
        return []


def ingest_file(path: Path) -> list[KnowledgeItem]:
    """Ingest a single file from the knowledge folder.

    Returns a list of KnowledgeItem instances (not yet committed to DB).
    A single file can produce multiple items (e.g., a bookmarks export).
    """
    if not path.exists() or not path.is_file():
        return []

    suffix = path.suffix.lower()
    items = []

    # URL shortcut files
    if suffix in (".url", ".webloc"):
        url = _extract_url_from_file(path)
        if url:
            items.append(KnowledgeItem(
                source_type=SourceType.BOOKMARK.value,
                source_url=url,
                title=path.stem,
                content_summary=f"Bookmarked URL: {url}",
                raw_content_path=str(path),
                tags=[],
            ))
        return items

    # Bookmark HTML exports
    if suffix in (".html", ".htm"):
        # Check if it's a bookmark export
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:500].lower()
        except Exception:
            head = ""

        if "<!doctype netscape-bookmark" in head or "bookmarks" in path.stem.lower():
            bookmarks = _parse_bookmarks_html(path)
            for bm in bookmarks:
                items.append(KnowledgeItem(
                    source_type=SourceType.BOOKMARK.value,
                    source_url=bm["url"],
                    title=bm["title"] or bm["url"],
                    content_summary=f"Bookmark: {bm['title']}",
                    raw_content_path=str(path),
                    tags=[],
                ))
            return items

    # JSON files (could be bookmark exports)
    if suffix == ".json":
        bookmarks = _parse_json_bookmarks(path)
        if bookmarks:
            for bm in bookmarks:
                items.append(KnowledgeItem(
                    source_type=SourceType.BOOKMARK.value,
                    source_url=bm["url"],
                    title=bm["title"] or bm["url"],
                    content_summary=f"Bookmark: {bm['title']}",
                    raw_content_path=str(path),
                    tags=[],
                ))
            return items
        # If not bookmarks, treat as a note
        content = _read_text_file(path)
        if content:
            items.append(KnowledgeItem(
                source_type=SourceType.NOTE.value,
                title=path.stem,
                content_summary=content[:500],
                raw_content_path=str(path),
                tags=[],
            ))
        return items

    # Text/Markdown/RST files
    if suffix in SUPPORTED_EXTENSIONS:
        content = _read_text_file(path)
        if content:
            # Try to extract title from first heading
            title = path.stem
            first_line = content.strip().split("\n")[0]
            if first_line.startswith("# "):
                title = first_line[2:].strip()
            elif first_line.startswith("## "):
                title = first_line[3:].strip()

            # Detect if it contains URLs (could be a link dump)
            urls = re.findall(r"https?://[^\s\)\"'>]+", content)

            items.append(KnowledgeItem(
                source_type=SourceType.NOTE.value,
                title=title,
                content_summary=content[:500],
                raw_content_path=str(path),
                tags=[],
            ))

            # Also extract individual URLs as bookmarks
            for url in urls[:50]:  # Cap at 50 URLs per file
                items.append(KnowledgeItem(
                    source_type=SourceType.BOOKMARK.value,
                    source_url=url,
                    title=url.split("/")[-1][:100] or url[:100],
                    content_summary=f"URL found in {path.name}: {url}",
                    raw_content_path=str(path),
                    tags=[],
                ))

        return items

    logger.debug(f"Skipping unsupported file type: {path}")
    return items


def scan_knowledge_folder(knowledge_dir: Path) -> list[dict]:
    """Scan the knowledge folder and ingest all new files.

    Returns a list of newly ingested items as dicts.
    """
    if not knowledge_dir.exists():
        return []

    new_items = []

    with get_session() as session:
        # Get already-ingested paths
        existing_paths = set()
        existing = session.query(KnowledgeItem.raw_content_path).all()
        for (p,) in existing:
            if p:
                existing_paths.add(p)

        # Walk the knowledge directory
        for path in sorted(knowledge_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            if str(path) in existing_paths:
                continue

            items = ingest_file(path)
            for item in items:
                # Avoid duplicate URLs
                if item.source_url:
                    dup = (
                        session.query(KnowledgeItem)
                        .filter(KnowledgeItem.source_url == item.source_url)
                        .first()
                    )
                    if dup:
                        continue

                session.add(item)
                new_items.append({
                    "title": item.title,
                    "type": item.source_type,
                    "url": item.source_url,
                    "path": item.raw_content_path,
                })

    if new_items:
        logger.info(f"Ingested {len(new_items)} new knowledge items")

    return new_items
