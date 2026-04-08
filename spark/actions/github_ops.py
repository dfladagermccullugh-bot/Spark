"""GitHub operations: branch creation, commits, and pull requests.

Uses gitpython for local git operations. GitHub API integration for
remote PR creation uses the `gh` CLI or direct API calls.
"""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path

from git import Repo

from spark.db.connection import get_session
from spark.db.models import AgentTask, Project, TaskStatus, TaskType

logger = logging.getLogger(__name__)


def _slugify(text: str, max_length: int = 40) -> str:
    """Convert text to a branch-name-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_length]


class GitResult:
    """Result of a git operation."""

    def __init__(self, success: bool, message: str, **details):
        self.success = success
        self.message = message
        self.details = details


def create_branch(project_path: str, branch_name: str) -> GitResult:
    """Create a new branch from the current HEAD."""
    try:
        repo = Repo(project_path)
        current = repo.active_branch.name

        if branch_name in [b.name for b in repo.branches]:
            return GitResult(False, f"Branch '{branch_name}' already exists")

        repo.create_head(branch_name)
        repo.heads[branch_name].checkout()
        return GitResult(
            True,
            f"Created and checked out branch '{branch_name}'",
            branch=branch_name,
            from_branch=current,
        )
    except Exception as e:
        return GitResult(False, f"Failed to create branch: {e}")


def commit_changes(
    project_path: str,
    message: str,
    files: list[str] | None = None,
) -> GitResult:
    """Stage and commit changes.

    If files is None, stages all modified/new files.
    """
    try:
        repo = Repo(project_path)

        if files:
            repo.index.add(files)
        else:
            # Stage all changes (modified + untracked)
            repo.git.add("-A")

        if not repo.index.diff("HEAD") and not repo.untracked_files:
            return GitResult(False, "No changes to commit")

        commit = repo.index.commit(message)
        return GitResult(
            True,
            f"Committed: {message}",
            commit_hash=commit.hexsha[:8],
            files_changed=list(commit.stats.files.keys()),
        )
    except Exception as e:
        return GitResult(False, f"Failed to commit: {e}")


def push_branch(project_path: str, branch_name: str | None = None) -> GitResult:
    """Push a branch to origin."""
    try:
        repo = Repo(project_path)
        branch = branch_name or repo.active_branch.name

        if "origin" not in [r.name for r in repo.remotes]:
            return GitResult(False, "No 'origin' remote configured")

        repo.git.push("origin", branch, set_upstream=True)
        return GitResult(True, f"Pushed branch '{branch}' to origin", branch=branch)
    except Exception as e:
        return GitResult(False, f"Failed to push: {e}")


def switch_back(project_path: str, original_branch: str) -> GitResult:
    """Switch back to the original branch after work is done."""
    try:
        repo = Repo(project_path)
        repo.heads[original_branch].checkout()
        return GitResult(True, f"Switched back to '{original_branch}'")
    except Exception as e:
        return GitResult(False, f"Failed to switch branch: {e}")


def create_contribution(
    project_id: str,
    description: str,
    files_changed: list[str],
    branch_prefix: str = "spark",
) -> GitResult:
    """Full workflow: create branch, commit changes, push.

    This is the high-level function called after code generation.
    Assumes files have already been written to disk.
    """
    with get_session() as session:
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            return GitResult(False, "Project not found")
        project_path = project.local_path
        project_name = project.name

    repo_path = Path(project_path)
    if not repo_path.exists():
        return GitResult(False, f"Project path not found: {project_path}")

    try:
        repo = Repo(project_path)
    except Exception:
        return GitResult(False, "Not a git repository")

    original_branch = repo.active_branch.name
    slug = _slugify(description)
    branch_name = f"{branch_prefix}/{slug}"

    # Create branch
    result = create_branch(project_path, branch_name)
    if not result.success:
        return result

    # Commit
    commit_msg = f"spark: {description}\n\nAutomated contribution by Spark agent."
    result = commit_changes(project_path, commit_msg, files_changed)
    if not result.success:
        switch_back(project_path, original_branch)
        return result

    commit_hash = result.details.get("commit_hash", "unknown")

    # Push
    push_result = push_branch(project_path, branch_name)

    # Switch back to original branch
    switch_back(project_path, original_branch)

    if push_result.success:
        # Record the task
        with get_session() as session:
            task = AgentTask(
                project_id=project_id,
                task_type=TaskType.PR.value,
                description=description,
                status=TaskStatus.DONE.value,
                result={
                    "branch": branch_name,
                    "commit": commit_hash,
                    "files": files_changed,
                    "pushed": True,
                },
                completed_at=datetime.utcnow(),
            )
            session.add(task)

        return GitResult(
            True,
            f"Created branch '{branch_name}' with commit {commit_hash} and pushed to origin",
            branch=branch_name,
            commit=commit_hash,
            files=files_changed,
        )
    else:
        # Still committed locally even if push failed
        return GitResult(
            True,
            f"Created branch '{branch_name}' with commit {commit_hash} (push failed: {push_result.message})",
            branch=branch_name,
            commit=commit_hash,
            files=files_changed,
            push_failed=True,
        )
