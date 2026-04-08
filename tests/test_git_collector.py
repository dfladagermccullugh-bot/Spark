"""Tests for git activity collection."""

import os
from datetime import datetime
from pathlib import Path

import pytest
from git import Repo

from spark.collectors.git_collector import collect_git_activity, get_repo_info, scan_for_repos
from spark.db.connection import get_session, init_db
from spark.db.models import ActivityEvent, Project


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path


@pytest.fixture
def projects_dir(tmp_path):
    """Create a projects directory with a sample git repo."""
    projects = tmp_path / "projects"
    projects.mkdir()

    # Create a git repo with a commit
    repo_path = projects / "sample-project"
    repo_path.mkdir()
    repo = Repo.init(repo_path)

    # Create a file and commit
    test_file = repo_path / "main.py"
    test_file.write_text("print('hello')\n")
    repo.index.add(["main.py"])
    repo.index.commit("Initial commit")

    # Second commit
    test_file.write_text("print('hello world')\n")
    repo.index.add(["main.py"])
    repo.index.commit("Update greeting")

    return projects


class TestScanForRepos:
    def test_finds_git_repos(self, projects_dir):
        repos = scan_for_repos(projects_dir)
        assert len(repos) == 1
        assert repos[0].name == "sample-project"

    def test_ignores_non_git_dirs(self, projects_dir):
        (projects_dir / "not-a-repo").mkdir()
        repos = scan_for_repos(projects_dir)
        assert len(repos) == 1

    def test_ignores_hidden_dirs(self, projects_dir):
        hidden = projects_dir / ".hidden-repo"
        hidden.mkdir()
        Repo.init(hidden)
        repos = scan_for_repos(projects_dir)
        assert len(repos) == 1

    def test_handles_missing_dir(self, tmp_path):
        repos = scan_for_repos(tmp_path / "nonexistent")
        assert repos == []


class TestGetRepoInfo:
    def test_extracts_repo_info(self, projects_dir):
        repo_path = projects_dir / "sample-project"
        info = get_repo_info(repo_path)

        assert info["name"] == "sample-project"
        assert len(info["recent_commits"]) == 2
        assert info["recent_commits"][0]["message"] == "Update greeting"
        assert "main" in info["branches"] or "master" in info["branches"]

    def test_handles_invalid_repo(self, tmp_path):
        info = get_repo_info(tmp_path / "not-a-repo")
        assert info == {}


class TestCollectGitActivity:
    def test_collects_commits_for_tracked_project(self, db, projects_dir):
        repo_path = projects_dir / "sample-project"

        # Register the project
        with get_session() as session:
            project = Project(
                name="sample-project",
                local_path=str(repo_path),
                status="active",
            )
            session.add(project)

        # Collect activity
        events = collect_git_activity(projects_dir)
        assert len(events) == 2
        assert events[0]["type"] == "commit"

    def test_skips_untracked_repos(self, db, projects_dir):
        # Don't register the project
        events = collect_git_activity(projects_dir)
        assert len(events) == 0

    def test_doesnt_duplicate_commits(self, db, projects_dir):
        repo_path = projects_dir / "sample-project"

        with get_session() as session:
            project = Project(
                name="sample-project",
                local_path=str(repo_path),
                status="active",
            )
            session.add(project)

        # Collect twice
        events1 = collect_git_activity(projects_dir)
        events2 = collect_git_activity(projects_dir)

        assert len(events1) == 2
        assert len(events2) == 0  # No new events
