"""Collect activity signals from git repositories."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from git import InvalidGitRepositoryError, NoSuchPathError, Repo

from spark.db.connection import get_session
from spark.db.models import ActivityEvent, EventType, Project

logger = logging.getLogger(__name__)


def scan_for_repos(projects_dir: Path) -> list[Path]:
    """Find all git repositories under the projects directory."""
    repos = []
    if not projects_dir.exists():
        return repos

    for path in projects_dir.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        git_dir = path / ".git"
        if git_dir.exists():
            repos.append(path)
        else:
            # Check one level deeper
            for subpath in path.iterdir():
                if subpath.is_dir() and (subpath / ".git").exists():
                    repos.append(subpath)
    return repos


def get_repo_info(repo_path: Path) -> dict:
    """Extract current state from a git repository."""
    try:
        repo = Repo(repo_path)
    except (InvalidGitRepositoryError, NoSuchPathError):
        return {}

    info = {
        "path": str(repo_path),
        "name": repo_path.name,
        "branches": [b.name for b in repo.branches],
        "active_branch": None,
        "is_dirty": repo.is_dirty(),
        "untracked_files": repo.untracked_files[:20],
        "remotes": {},
        "recent_commits": [],
    }

    try:
        info["active_branch"] = repo.active_branch.name
    except TypeError:
        pass  # Detached HEAD

    for remote in repo.remotes:
        info["remotes"][remote.name] = list(remote.urls)

    # Last 20 commits
    try:
        for commit in repo.iter_commits(max_count=20):
            info["recent_commits"].append({
                "hash": commit.hexsha[:8],
                "message": commit.message.strip()[:200],
                "author": str(commit.author),
                "timestamp": commit.committed_datetime.isoformat(),
            })
    except Exception:
        pass  # Empty repo or other issue

    return info


def collect_git_activity(projects_dir: Path) -> list[dict]:
    """Scan all repos and record new activity events. Returns list of new events."""
    new_events = []
    repo_paths = scan_for_repos(projects_dir)

    with get_session() as session:
        for repo_path in repo_paths:
            project = (
                session.query(Project)
                .filter(Project.local_path == str(repo_path))
                .first()
            )
            if project is None:
                continue

            try:
                repo = Repo(repo_path)
            except InvalidGitRepositoryError:
                continue

            # Get the latest recorded event timestamp for this project
            latest_event = (
                session.query(ActivityEvent)
                .filter(
                    ActivityEvent.project_id == project.id,
                    ActivityEvent.event_type == EventType.COMMIT.value,
                )
                .order_by(ActivityEvent.occurred_at.desc())
                .first()
            )

            latest_ts = latest_event.occurred_at if latest_event else None

            # Collect new commits
            try:
                for commit in repo.iter_commits(max_count=50):
                    commit_dt = commit.committed_datetime.replace(tzinfo=timezone.utc)
                    naive_dt = commit_dt.replace(tzinfo=None)

                    if latest_ts and naive_dt <= latest_ts:
                        break

                    event = ActivityEvent(
                        project_id=project.id,
                        event_type=EventType.COMMIT.value,
                        event_data={
                            "hash": commit.hexsha[:8],
                            "message": commit.message.strip()[:200],
                            "author": str(commit.author),
                            "files_changed": len(commit.stats.files),
                        },
                        occurred_at=naive_dt,
                    )
                    session.add(event)
                    new_events.append({
                        "project": project.name,
                        "type": "commit",
                        "hash": commit.hexsha[:8],
                        "message": commit.message.strip()[:100],
                    })

                    # Update project's last activity
                    if project.last_activity_at is None or naive_dt > project.last_activity_at:
                        project.last_activity_at = naive_dt

            except Exception as e:
                logger.warning(f"Error collecting commits for {repo_path}: {e}")

    return new_events
