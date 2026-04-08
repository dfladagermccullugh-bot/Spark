"""Connect knowledge items to projects - find relevant cross-references.

The connector is the "connection-making" engine that finds links between
disparate knowledge items and active projects. This is what makes Spark
say "that article you bookmarked is relevant to your auth module."
"""

from __future__ import annotations

import logging

from spark.db.connection import get_session
from spark.db.models import KnowledgeItem, Project, ProjectStatus
from spark.knowledge.indexer import search_knowledge, search_project_files

logger = logging.getLogger(__name__)

# Relevance threshold - lower distance = more relevant (ChromaDB uses L2 distance)
RELEVANCE_THRESHOLD = 1.5


def find_relevant_knowledge(project_id: str, n_results: int = 5) -> list[dict]:
    """Find knowledge items relevant to a specific project.

    Uses the project's description, current goal, and recent file content
    to search the knowledge base for relevant items.

    Returns a list of dicts: {item_id, title, source_type, source_url, relevance_reason, distance}
    """
    with get_session() as session:
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            return []

        # Build search queries from project context
        queries = []
        if project.description:
            queries.append(project.description)
        if project.current_goal:
            queries.append(project.current_goal)
        # Combine name + description for broader match
        queries.append(f"{project.name} {project.description or ''} {project.current_goal or ''}")

    if not queries:
        return []

    # Search knowledge for each query, deduplicate by item_id
    seen_ids = set()
    relevant = []

    for query in queries:
        results = search_knowledge(query, n_results=n_results)
        for item in results:
            if item["id"] in seen_ids:
                continue
            if item.get("distance") is not None and item["distance"] > RELEVANCE_THRESHOLD:
                continue

            seen_ids.add(item["id"])
            relevant.append({
                "item_id": item["id"],
                "title": item["title"],
                "source_type": item["source_type"],
                "source_url": item["source_url"],
                "relevance_reason": f"Matches project context: {query[:80]}",
                "distance": item.get("distance"),
                "content_preview": item.get("content", "")[:200],
            })

    # Sort by relevance (lower distance = better)
    relevant.sort(key=lambda r: r.get("distance") or 999)
    return relevant[:n_results]


def find_cross_project_connections(project_id: str) -> list[dict]:
    """Find connections between a project and other projects' files.

    This powers suggestions like "your color palette component from ProjectA
    could be used in ProjectB's dashboard."

    Returns list of dicts: {source_project, target_project, file_path, reason, distance}
    """
    with get_session() as session:
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            return []

        other_projects = (
            session.query(Project)
            .filter(
                Project.id != project_id,
                Project.status.in_([ProjectStatus.ACTIVE.value, ProjectStatus.PAUSED.value]),
            )
            .all()
        )
        other_ids = {p.id: p.name for p in other_projects}

    if not other_ids:
        return []

    # Use the project's description/goal as a search query against other projects' files
    query_parts = []
    if project.description:
        query_parts.append(project.description)
    if project.current_goal:
        query_parts.append(project.current_goal)
    query = " ".join(query_parts) or project.name

    connections = []

    # Search across all project files (not restricted to one project)
    results = search_project_files(query, project_id=None, n_results=10)

    for result in results:
        other_pid = result.get("project_id", "")
        if other_pid == project_id or other_pid not in other_ids:
            continue
        if result.get("distance") is not None and result["distance"] > RELEVANCE_THRESHOLD:
            continue

        connections.append({
            "source_project": project.name,
            "target_project": other_ids[other_pid],
            "target_project_id": other_pid,
            "file_path": result.get("file_path", ""),
            "reason": f"File content relates to: {query[:80]}",
            "distance": result.get("distance"),
            "content_preview": result.get("content", "")[:200],
        })

    connections.sort(key=lambda c: c.get("distance") or 999)
    return connections[:5]


def update_relevance_scores() -> int:
    """Batch update relevance scores for all knowledge items against all active projects.

    Stores scores in the KnowledgeItem.relevance_scores JSON field.
    Returns the number of items updated.
    """
    with get_session() as session:
        projects = (
            session.query(Project)
            .filter(Project.status == ProjectStatus.ACTIVE.value)
            .all()
        )
        project_data = [(p.id, p.name, p.description, p.current_goal) for p in projects]

    if not project_data:
        return 0

    updated = 0

    with get_session() as session:
        items = session.query(KnowledgeItem).filter(
            KnowledgeItem.embedding_id.isnot(None)
        ).all()

        for item in items:
            scores = {}
            search_text = f"{item.title} {item.content_summary or ''}"[:500]

            # Check relevance against each project's files
            for pid, pname, desc, goal in project_data:
                results = search_project_files(search_text, project_id=pid, n_results=1)
                if results and results[0].get("distance") is not None:
                    distance = results[0]["distance"]
                    # Convert distance to a 0-1 relevance score (lower distance = higher relevance)
                    relevance = max(0.0, 1.0 - (distance / 2.0))
                    if relevance > 0.2:  # Only store meaningful scores
                        scores[pid] = round(relevance, 3)

            if scores:
                item.relevance_scores = scores
                updated += 1

    if updated:
        logger.info(f"Updated relevance scores for {updated} knowledge items")
    return updated


def get_knowledge_context_for_project(project_id: str, max_items: int = 5) -> str:
    """Build a formatted knowledge context string for use in nudge prompts.

    This is the integration point between the knowledge engine and the
    nudge generator.
    """
    relevant = find_relevant_knowledge(project_id, n_results=max_items)
    if not relevant:
        return ""

    lines = ["RELEVANT KNOWLEDGE (articles, bookmarks, notes you've saved):"]
    for item in relevant:
        line = f"- {item['title']}"
        if item.get("source_url"):
            line += f" ({item['source_url'][:80]})"
        if item.get("content_preview"):
            preview = item["content_preview"].replace("\n", " ")[:100]
            line += f"\n  Preview: {preview}"
        lines.append(line)

    cross = find_cross_project_connections(project_id)
    if cross:
        lines.append("\nCROSS-PROJECT CONNECTIONS:")
        for conn in cross:
            lines.append(
                f"- {conn['target_project']}/{conn['file_path']} "
                f"may be relevant: {conn['reason'][:80]}"
            )

    return "\n".join(lines)
