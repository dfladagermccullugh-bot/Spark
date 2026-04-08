"""Content enrichment - fetch and summarize URLs in the knowledge base.

When knowledge items have URLs (bookmarks, saved articles), this module
fetches the actual page content and uses Claude to generate a useful summary.
This makes the knowledge base much more valuable for cross-referencing.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

from spark.db.connection import get_session
from spark.db.models import KnowledgeItem

logger = logging.getLogger(__name__)

# Max content length to send to Claude for summarization
MAX_CONTENT_LENGTH = 8000

# Skip these domains (paywalls, login walls, or uninteresting)
SKIP_DOMAINS = {
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
}

SUMMARIZE_PROMPT = """\
Summarize this web page content in 2-3 sentences for a developer's knowledge base. \
Focus on the key technical insight, tool, or concept. Be specific and actionable.

Title: {title}
URL: {url}

Content:
{content}

Return ONLY the summary, no preamble.\
"""


class _TextExtractor(HTMLParser):
    """Simple HTML-to-text converter."""

    def __init__(self):
        super().__init__()
        self._text_parts: list[str] = []
        self._skip = False
        self._skip_tags = {"script", "style", "nav", "header", "footer", "aside"}

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self._text_parts.append(text)

    def get_text(self) -> str:
        return " ".join(self._text_parts)


def _extract_text_from_html(html: str) -> str:
    """Extract readable text from HTML, stripping tags and noise."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        # Fallback: crude regex strip
        return re.sub(r"<[^>]+>", " ", html)[:MAX_CONTENT_LENGTH]
    return parser.get_text()[:MAX_CONTENT_LENGTH]


def _should_skip_url(url: str) -> bool:
    """Check if a URL should be skipped for enrichment."""
    if not url:
        return True
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().lstrip("www.")
        return domain in SKIP_DOMAINS
    except Exception:
        return True


def fetch_and_summarize(
    url: str,
    title: str,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
) -> str | None:
    """Fetch a URL's content and generate a summary using Claude.

    Returns the summary text, or None if fetching/summarization fails.
    """
    if _should_skip_url(url):
        return None

    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; SparkBot/1.0; knowledge-enrichment)",
                "Accept": "text/html,application/xhtml+xml,text/plain",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                logger.debug(f"Skipping non-text content: {content_type} for {url}")
                return None

            raw = resp.read(200_000)  # Cap at 200KB
            encoding = resp.headers.get_content_charset() or "utf-8"
            try:
                html = raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                html = raw.decode("utf-8", errors="replace")

    except Exception as e:
        logger.debug(f"Failed to fetch {url}: {e}")
        return None

    # Extract text from HTML
    text = _extract_text_from_html(html)
    if len(text) < 50:
        logger.debug(f"Not enough content from {url}")
        return None

    # Summarize with LLM
    try:
        from spark.llm import completion, get_text

        response = completion(
            model=model,
            messages=[{
                "role": "user",
                "content": SUMMARIZE_PROMPT.format(
                    title=title,
                    url=url,
                    content=text[:MAX_CONTENT_LENGTH],
                ),
            }],
            api_key=api_key,
            max_tokens=200,
        )
        return get_text(response)

    except Exception as e:
        logger.error(f"Failed to summarize {url}: {e}")
        return None


def enrich_knowledge_items(
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
    batch_size: int = 5,
) -> int:
    """Enrich knowledge items that have URLs but no content summary.

    Fetches page content and generates summaries for items that:
    - Have a source_url
    - Don't have a content_summary (or it's very short)
    - Haven't been enriched yet

    Returns the number of items enriched.
    """
    with get_session() as session:
        candidates = (
            session.query(KnowledgeItem)
            .filter(
                KnowledgeItem.source_url.isnot(None),
                KnowledgeItem.enriched_at.is_(None),
            )
            .limit(batch_size)
            .all()
        )

        if not candidates:
            return 0

        item_data = [
            (item.id, item.source_url, item.title, item.content_summary)
            for item in candidates
        ]

    enriched = 0

    for item_id, url, title, existing_summary in item_data:
        # Skip if already has a good summary
        if existing_summary and len(existing_summary) > 100:
            with get_session() as session:
                item = session.query(KnowledgeItem).filter(
                    KnowledgeItem.id == item_id
                ).first()
                if item:
                    item.enriched_at = datetime.utcnow()
            continue

        summary = fetch_and_summarize(url, title, api_key, model)

        with get_session() as session:
            item = session.query(KnowledgeItem).filter(
                KnowledgeItem.id == item_id
            ).first()
            if item:
                if summary:
                    item.content_summary = summary
                    enriched += 1
                    logger.info(f"Enriched: {title[:60]}")
                item.enriched_at = datetime.utcnow()

    if enriched:
        logger.info(f"Enriched {enriched} knowledge items with content summaries")
    return enriched
