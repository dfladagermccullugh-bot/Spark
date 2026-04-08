"""Build rich context snapshots of projects for the LLM."""

from __future__ import annotations

import logging
from pathlib import Path

from git import InvalidGitRepositoryError, Repo

from spark.db.connection import get_session
from spark.db.models import ActivityEvent, EventType, Message, MessageDirection, Project

logger = logging.getLogger(__name__)

# Files to always include in context if they exist
KEY_FILES = [
    "README.md",
    "readme.md",
    "README",
    "TODO.md",
    "CHANGELOG.md",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "Makefile",
]

MAX_FILE_SNIPPET = 2000  # Max chars to include from any single file


def _read_file_safe(path: Path, max_chars: int = MAX_FILE_SNIPPET) -> str | None:
    """Read a file safely, returning None on failure."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            return content[:max_chars] + f"\n... ({len(content) - max_chars} more chars)"
        return content
    except Exception:
        return None


def _get_file_tree(repo_path: Path, max_depth: int = 3, max_files: int = 100) -> str:
    """Get a tree representation of the project directory."""
    lines = []
    count = 0

    def _walk(path: Path, prefix: str, depth: int) -> None:
        nonlocal count
        if depth > max_depth or count > max_files:
            return

        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        for entry in entries:
            if entry.name.startswith(".") or entry.name in {
                "__pycache__", "node_modules", ".git", "venv", ".venv",
                "dist", "build", ".eggs", "target",
            }:
                continue
            count += 1
            if count > max_files:
                lines.append(f"{prefix}... ({count}+ files)")
                return
            lines.append(f"{prefix}{entry.name}{'/' if entry.is_dir() else ''}")
            if entry.is_dir():
                _walk(entry, prefix + "  ", depth + 1)

    _walk(repo_path, "", 0)
    return "\n".join(lines)


def _get_git_context(repo_path: Path) -> dict:
    """Get git-specific context."""
    try:
        repo = Repo(repo_path)
    except InvalidGitRepositoryError:
        return {}

    context = {
        "active_branch": None,
        "is_dirty": repo.is_dirty(),
        "unstaged_summary": "",
        "recent_commits": [],
        "stale_branches": [],
    }

    try:
        context["active_branch"] = repo.active_branch.name
    except TypeError:
        pass

    # Unstaged changes summary
    if repo.is_dirty():
        try:
            diff = repo.git.diff("--stat")
            context["unstaged_summary"] = diff[:1000]
        except Exception:
            pass

    # Recent commits
    try:
        for commit in repo.iter_commits(max_count=10):
            context["recent_commits"].append({
                "hash": commit.hexsha[:8],
                "message": commit.message.strip()[:150],
                "author": str(commit.author),
                "date": commit.committed_datetime.strftime("%Y-%m-%d %H:%M"),
                "files": list(commit.stats.files.keys())[:10],
            })
    except Exception:
        pass

    # Stale branches (no commits in 14+ days)
    try:
        for branch in repo.branches:
            try:
                last_commit = branch.commit
                age_days = (
                    repo.head.commit.committed_datetime - last_commit.committed_datetime
                ).days
                if age_days > 14 and branch.name != context["active_branch"]:
                    context["stale_branches"].append({
                        "name": branch.name,
                        "days_stale": age_days,
                        "last_message": last_commit.message.strip()[:100],
                    })
            except Exception:
                continue
    except Exception:
        pass

    return context


def build_project_context(project_id: str) -> dict:
    """Build a comprehensive context snapshot for a project.

    This is what gets sent to the LLM to generate context-aware nudges.
    """
    with get_session() as session:
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {}

        # Basic info
        context = {
            "project_name": project.name,
            "description": project.description or "No description provided",
            "current_goal": project.current_goal or "No specific goal set",
            "status": project.status,
            "local_path": project.local_path,
            "github_repo": project.github_repo,
            "last_activity": (
                project.last_activity_at.isoformat() if project.last_activity_at else "never"
            ),
            "rhythm": project.activity_baseline or {},
        }

        # Recent activity events
        recent_events = (
            session.query(ActivityEvent)
            .filter(ActivityEvent.project_id == project_id)
            .order_by(ActivityEvent.occurred_at.desc())
            .limit(20)
            .all()
        )
        context["recent_events"] = [
            {
                "type": e.event_type,
                "data": e.event_data,
                "at": e.occurred_at.isoformat(),
            }
            for e in recent_events
        ]

        # Recent messages (conversation history)
        recent_messages = (
            session.query(Message)
            .filter(Message.project_id == project_id)
            .order_by(Message.sent_at.desc())
            .limit(10)
            .all()
        )
        context["recent_messages"] = [
            {
                "direction": m.direction,
                "content": m.content,
                "type": m.message_type,
                "at": m.sent_at.isoformat() if m.sent_at else None,
            }
            for m in recent_messages
        ]

    # Filesystem context
    repo_path = Path(project.local_path)
    if repo_path.exists():
        context["file_tree"] = _get_file_tree(repo_path)

        # Read key files
        context["key_files"] = {}
        for filename in KEY_FILES:
            filepath = repo_path / filename
            if filepath.exists():
                content = _read_file_safe(filepath)
                if content:
                    context["key_files"][filename] = content

        # Git context
        context["git"] = _get_git_context(repo_path)

    return context


def build_cross_project_context() -> list[dict]:
    """Build a summary of all active projects for cross-project suggestions."""
    summaries = []
    with get_session() as session:
        projects = session.query(Project).filter(
            Project.status.in_(["active", "paused"])
        ).all()

        for project in projects:
            hours_since = None
            if project.last_activity_at:
                from datetime import datetime
                hours_since = (
                    datetime.utcnow() - project.last_activity_at
                ).total_seconds() / 3600

            summaries.append({
                "name": project.name,
                "description": project.description or "No description",
                "current_goal": project.current_goal or "No goal set",
                "status": project.status,
                "hours_since_activity": round(hours_since, 1) if hours_since else None,
                "rhythm": project.activity_baseline or {},
            })

    return summaries
