"""External feed connectors for browser bookmarks, YouTube, and Twitter/X.

These connectors pull data from external sources and convert them into
KnowledgeItem records that can be indexed and searched.

All connectors are designed to work with exported data files (not live APIs)
for Phase 2. Live API integration can be added later.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from spark.db.connection import get_session
from spark.db.models import KnowledgeItem, SourceType

logger = logging.getLogger(__name__)


def _deduplicated_add(session, item: KnowledgeItem) -> bool:
    """Add a knowledge item if its URL is not already in the database."""
    if item.source_url:
        existing = (
            session.query(KnowledgeItem)
            .filter(KnowledgeItem.source_url == item.source_url)
            .first()
        )
        if existing:
            return False
    session.add(item)
    return True


def import_chrome_bookmarks(bookmarks_path: Path) -> int:
    """Import Chrome bookmarks from an exported JSON file.

    Chrome bookmark export location:
    - macOS: ~/Library/Application Support/Google/Chrome/Default/Bookmarks
    - Linux: ~/.config/google-chrome/Default/Bookmarks
    - Windows: %LOCALAPPDATA%/Google/Chrome/User Data/Default/Bookmarks
    """
    try:
        data = json.loads(bookmarks_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to read Chrome bookmarks: {e}")
        return 0

    bookmarks = []

    def _walk(node: dict, folder: str = "") -> None:
        node_type = node.get("type", "")
        name = node.get("name", "")
        current_folder = f"{folder}/{name}" if folder else name

        if node_type == "url":
            bookmarks.append({
                "url": node.get("url", ""),
                "title": name,
                "folder": folder,
                "date_added": node.get("date_added", ""),
            })

        for child in node.get("children", []):
            _walk(child, current_folder)

    roots = data.get("roots", {})
    for root_name, root_node in roots.items():
        if isinstance(root_node, dict):
            _walk(root_node, root_name)

    count = 0
    with get_session() as session:
        for bm in bookmarks:
            if not bm["url"].startswith("http"):
                continue
            item = KnowledgeItem(
                source_type=SourceType.BOOKMARK.value,
                source_url=bm["url"],
                title=bm["title"] or bm["url"][:100],
                content_summary=f"Chrome bookmark in {bm['folder']}: {bm['title']}",
                raw_content_path=str(bookmarks_path),
                tags=[bm["folder"]] if bm["folder"] else [],
            )
            if _deduplicated_add(session, item):
                count += 1

    logger.info(f"Imported {count} Chrome bookmarks")
    return count


def import_firefox_bookmarks(bookmarks_path: Path) -> int:
    """Import Firefox bookmarks from an exported JSON file.

    Export via: Bookmarks > Show All Bookmarks > Import and Backup > Backup
    """
    try:
        data = json.loads(bookmarks_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to read Firefox bookmarks: {e}")
        return 0

    bookmarks = []

    def _walk(node: dict, folder: str = "") -> None:
        title = node.get("title", "")
        current_folder = f"{folder}/{title}" if folder else title

        if node.get("type") == "text/x-moz-place" and node.get("uri"):
            bookmarks.append({
                "url": node["uri"],
                "title": title,
                "folder": folder,
            })

        for child in node.get("children", []):
            _walk(child, current_folder)

    _walk(data)

    count = 0
    with get_session() as session:
        for bm in bookmarks:
            if not bm["url"].startswith("http"):
                continue
            item = KnowledgeItem(
                source_type=SourceType.BOOKMARK.value,
                source_url=bm["url"],
                title=bm["title"] or bm["url"][:100],
                content_summary=f"Firefox bookmark in {bm['folder']}: {bm['title']}",
                raw_content_path=str(bookmarks_path),
                tags=[bm["folder"]] if bm["folder"] else [],
            )
            if _deduplicated_add(session, item):
                count += 1

    logger.info(f"Imported {count} Firefox bookmarks")
    return count


def import_youtube_takeout(takeout_path: Path) -> int:
    """Import YouTube liked/saved videos from Google Takeout.

    Google Takeout exports a CSV or JSON of liked videos.
    Supports both the playlist CSV and the history JSON formats.
    """
    count = 0
    suffix = takeout_path.suffix.lower()

    if suffix == ".csv":
        count = _import_youtube_csv(takeout_path)
    elif suffix == ".json":
        count = _import_youtube_json(takeout_path)
    elif suffix == ".html":
        count = _import_youtube_html(takeout_path)
    else:
        logger.warning(f"Unsupported YouTube export format: {suffix}")

    logger.info(f"Imported {count} YouTube items")
    return count


def _import_youtube_csv(path: Path) -> int:
    """Import YouTube playlist CSV (Video Id, Playlist Video Creation Timestamp, etc.)."""
    count = 0
    try:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            with get_session() as session:
                for row in reader:
                    video_id = row.get("Video Id", row.get("video_id", ""))
                    title = row.get("Title", row.get("title", ""))
                    if not video_id:
                        continue

                    url = f"https://www.youtube.com/watch?v={video_id}"
                    item = KnowledgeItem(
                        source_type=SourceType.YOUTUBE.value,
                        source_url=url,
                        title=title or f"YouTube video {video_id}",
                        content_summary=f"YouTube video: {title}",
                        raw_content_path=str(path),
                        tags=["youtube"],
                    )
                    if _deduplicated_add(session, item):
                        count += 1
    except Exception as e:
        logger.warning(f"Failed to parse YouTube CSV: {e}")
    return count


def _import_youtube_json(path: Path) -> int:
    """Import YouTube history/likes JSON (Google Takeout format)."""
    count = 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("items", data.get("videos", []))

        with get_session() as session:
            for entry in items:
                title = entry.get("title", entry.get("snippet", {}).get("title", ""))
                url = entry.get("titleUrl", entry.get("url", ""))

                # Extract from subtitles/snippet if needed
                if not url:
                    video_id = entry.get("id", entry.get("videoId", ""))
                    if video_id:
                        url = f"https://www.youtube.com/watch?v={video_id}"

                if not url:
                    continue

                item = KnowledgeItem(
                    source_type=SourceType.YOUTUBE.value,
                    source_url=url,
                    title=title or url[:100],
                    content_summary=f"YouTube: {title}",
                    raw_content_path=str(path),
                    tags=["youtube"],
                )
                if _deduplicated_add(session, item):
                    count += 1
    except Exception as e:
        logger.warning(f"Failed to parse YouTube JSON: {e}")
    return count


def _import_youtube_html(path: Path) -> int:
    """Import YouTube watch history HTML (Google Takeout format)."""
    count = 0
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        # Extract YouTube links and their text
        pattern = r'<a href="(https://www\.youtube\.com/watch\?v=[^"]+)"[^>]*>([^<]*)</a>'
        matches = re.findall(pattern, content)

        with get_session() as session:
            for url, title in matches:
                item = KnowledgeItem(
                    source_type=SourceType.YOUTUBE.value,
                    source_url=url,
                    title=title.strip() or url[:100],
                    content_summary=f"YouTube: {title.strip()}",
                    raw_content_path=str(path),
                    tags=["youtube"],
                )
                if _deduplicated_add(session, item):
                    count += 1
    except Exception as e:
        logger.warning(f"Failed to parse YouTube HTML: {e}")
    return count


def import_twitter_bookmarks(bookmarks_path: Path) -> int:
    """Import Twitter/X bookmarks from a data export.

    Twitter data exports include a bookmarks.js file.
    Also supports manually exported JSON lists of tweets.
    """
    try:
        content = bookmarks_path.read_text(encoding="utf-8")

        # Twitter exports wrap JSON in a variable assignment
        if content.startswith("window."):
            # e.g., window.YTD.bookmarks.part0 = [...]
            content = content.split("=", 1)[1].strip()

        data = json.loads(content)
    except Exception as e:
        logger.error(f"Failed to read Twitter bookmarks: {e}")
        return 0

    count = 0
    items_list = data if isinstance(data, list) else []

    with get_session() as session:
        for entry in items_list:
            tweet = entry.get("tweet", entry)
            tweet_id = tweet.get("id", tweet.get("id_str", ""))
            full_text = tweet.get("full_text", tweet.get("text", ""))

            if not tweet_id:
                continue

            url = f"https://twitter.com/i/status/{tweet_id}"

            # Extract any URLs from the tweet
            urls_in_tweet = re.findall(r"https?://[^\s]+", full_text)
            expanded_urls = []
            for entity_url in tweet.get("entities", {}).get("urls", []):
                expanded = entity_url.get("expanded_url", entity_url.get("url", ""))
                if expanded:
                    expanded_urls.append(expanded)

            title = full_text[:100] if full_text else f"Tweet {tweet_id}"

            item = KnowledgeItem(
                source_type=SourceType.TWITTER.value,
                source_url=url,
                title=title,
                content_summary=full_text[:500] if full_text else "",
                raw_content_path=str(bookmarks_path),
                tags=["twitter"] + expanded_urls[:5],
            )
            if _deduplicated_add(session, item):
                count += 1

    logger.info(f"Imported {count} Twitter bookmarks")
    return count


def auto_detect_and_import(file_path: Path) -> int:
    """Auto-detect the type of export file and import accordingly.

    Used when files are dropped into the knowledge folder.
    """
    name = file_path.name.lower()
    suffix = file_path.suffix.lower()

    # Try to detect by filename
    if "bookmark" in name and suffix == ".json":
        # Could be Chrome or Firefox
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            if "roots" in data:
                return import_chrome_bookmarks(file_path)
            elif data.get("type") == "text/x-moz-place-container":
                return import_firefox_bookmarks(file_path)
            else:
                # Generic JSON bookmarks - handled by ingester
                return 0
        except Exception:
            return 0

    if "youtube" in name or "watch-history" in name or "liked" in name:
        return import_youtube_takeout(file_path)

    if "twitter" in name or "bookmark" in name and "tweet" in name:
        return import_twitter_bookmarks(file_path)

    # Not a recognized export format
    return 0
