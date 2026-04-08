"""Build and maintain a ChromaDB vector index over knowledge items and project files.

Uses ChromaDB's built-in embedding functions (Sentence Transformers by default,
no API key needed) to create semantic search over all knowledge.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import chromadb

from spark.db.connection import get_session
from spark.db.models import KnowledgeItem, Project

logger = logging.getLogger(__name__)

_client: chromadb.ClientAPI | None = None

# Collection names
KNOWLEDGE_COLLECTION = "knowledge_items"
PROJECT_FILES_COLLECTION = "project_files"


def init_chromadb(persist_dir: Path) -> chromadb.ClientAPI:
    """Initialize ChromaDB with persistent storage."""
    global _client
    persist_dir.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=str(persist_dir))
    logger.info(f"ChromaDB initialized at {persist_dir}")
    return _client


def get_client() -> chromadb.ClientAPI:
    """Get the ChromaDB client, raising if not initialized."""
    if _client is None:
        raise RuntimeError("ChromaDB not initialized. Call init_chromadb() first.")
    return _client


def _content_hash(text: str) -> str:
    """Create a stable hash for dedup."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def index_knowledge_items() -> int:
    """Index all un-indexed knowledge items into ChromaDB.

    Returns the number of newly indexed items.
    """
    client = get_client()
    collection = client.get_or_create_collection(
        name=KNOWLEDGE_COLLECTION,
        metadata={"description": "User knowledge items: bookmarks, notes, articles"},
    )

    indexed = 0

    with get_session() as session:
        # Find items without an embedding_id
        items = (
            session.query(KnowledgeItem)
            .filter(KnowledgeItem.embedding_id.is_(None))
            .all()
        )

        if not items:
            return 0

        # Batch process
        ids = []
        documents = []
        metadatas = []

        for item in items:
            # Build the document text for embedding
            parts = []
            if item.title:
                parts.append(item.title)
            if item.content_summary:
                parts.append(item.content_summary)
            if item.source_url:
                parts.append(item.source_url)

            doc_text = "\n".join(parts)
            if not doc_text.strip():
                continue

            # Truncate to ChromaDB's practical limit
            doc_text = doc_text[:8000]

            doc_id = f"ki_{item.id}"
            ids.append(doc_id)
            documents.append(doc_text)
            metadatas.append({
                "item_id": item.id,
                "source_type": item.source_type,
                "title": (item.title or "")[:200],
                "source_url": item.source_url or "",
            })

            # Mark as indexed
            item.embedding_id = doc_id

        if ids:
            # ChromaDB upsert handles duplicates gracefully
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
            indexed = len(ids)
            logger.info(f"Indexed {indexed} knowledge items into ChromaDB")

    return indexed


def index_project_files(project_id: str, project_path: str) -> int:
    """Index key source files from a project into ChromaDB.

    Indexes READMEs, entry points, config files, and recently changed files.
    Returns the number of files indexed.
    """
    client = get_client()
    collection = client.get_or_create_collection(
        name=PROJECT_FILES_COLLECTION,
        metadata={"description": "Project source files for cross-referencing"},
    )

    path = Path(project_path)
    if not path.exists():
        return 0

    # Key files to always index
    key_patterns = [
        "README.md", "readme.md", "README",
        "pyproject.toml", "package.json", "Cargo.toml", "go.mod",
        "TODO.md", "CHANGELOG.md",
    ]

    # Also find source entry points
    source_patterns = [
        "src/main.*", "src/index.*", "src/app.*",
        "main.*", "index.*", "app.*",
        "lib/main.*", "lib/index.*",
    ]

    files_to_index: list[Path] = []

    for pattern in key_patterns:
        f = path / pattern
        if f.exists():
            files_to_index.append(f)

    # Find source files (first match for each pattern)
    for pattern in source_patterns:
        matches = list(path.glob(pattern))
        files_to_index.extend(matches[:2])  # Max 2 per pattern

    # Deduplicate
    files_to_index = list(dict.fromkeys(files_to_index))

    if not files_to_index:
        return 0

    ids = []
    documents = []
    metadatas = []

    for file_path in files_to_index[:20]:  # Cap at 20 files per project
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")[:5000]
        except Exception:
            continue

        relative = str(file_path.relative_to(path))
        doc_id = f"pf_{project_id}_{_content_hash(relative)}"

        ids.append(doc_id)
        documents.append(f"File: {relative}\n\n{content}")
        metadatas.append({
            "project_id": project_id,
            "file_path": relative,
        })

    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        logger.info(f"Indexed {len(ids)} project files for project {project_id}")

    return len(ids)


def search_knowledge(query: str, n_results: int = 5) -> list[dict]:
    """Search knowledge items by semantic similarity.

    Returns a list of dicts with: id, title, source_type, source_url, distance, content.
    """
    client = get_client()

    try:
        collection = client.get_collection(KNOWLEDGE_COLLECTION)
    except Exception:
        return []

    try:
        results = collection.query(
            query_texts=[query],
            n_results=n_results,
        )
    except Exception as e:
        logger.warning(f"Knowledge search failed: {e}")
        return []

    items = []
    if results and results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else None
            document = results["documents"][0][i] if results["documents"] else ""

            items.append({
                "id": meta.get("item_id", doc_id),
                "title": meta.get("title", ""),
                "source_type": meta.get("source_type", ""),
                "source_url": meta.get("source_url", ""),
                "distance": distance,
                "content": document[:500],
            })

    return items


def search_project_files(query: str, project_id: str | None = None, n_results: int = 5) -> list[dict]:
    """Search project files by semantic similarity.

    If project_id is given, restrict to that project's files.
    """
    client = get_client()

    try:
        collection = client.get_collection(PROJECT_FILES_COLLECTION)
    except Exception:
        return []

    where = {"project_id": project_id} if project_id else None

    try:
        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
        )
    except Exception as e:
        logger.warning(f"Project file search failed: {e}")
        return []

    items = []
    if results and results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else None
            document = results["documents"][0][i] if results["documents"] else ""

            items.append({
                "project_id": meta.get("project_id", ""),
                "file_path": meta.get("file_path", ""),
                "distance": distance,
                "content": document[:500],
            })

    return items
