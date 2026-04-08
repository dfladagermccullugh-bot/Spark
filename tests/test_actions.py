"""Tests for the action engine: code generation, git ops, authorization."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from git import Repo

from spark.db.connection import get_session, init_db
from spark.db.models import AgentTask, Project, ProjectStatus, TaskStatus, TaskType


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path


@pytest.fixture
def sample_project(db, tmp_path):
    """Create a sample project with a git repo."""
    project_dir = tmp_path / "sample-project"
    project_dir.mkdir()

    # Create git repo
    repo = Repo.init(project_dir)
    (project_dir / "main.py").write_text("def hello():\n    print('hello')\n")
    (project_dir / "README.md").write_text("# Sample Project\nA test project.\n")
    repo.index.add(["main.py", "README.md"])
    repo.index.commit("Initial commit")

    # Register in DB
    with get_session() as session:
        project = Project(
            name="sample-project",
            local_path=str(project_dir),
            description="A test project for unit tests",
            current_goal="Add error handling",
            status=ProjectStatus.ACTIVE.value,
            last_activity_at=datetime.utcnow(),
        )
        session.add(project)
        session.flush()
        pid = project.id

    return pid, project_dir


# ── Code Generator Tests (filesystem tools only, no LLM) ──


class TestCodeGeneratorTools:
    """Test the filesystem tools used by the code generator."""

    def test_execute_read_file(self, sample_project):
        from spark.actions.code_generator import _execute_tool

        pid, project_dir = sample_project
        result = _execute_tool("read_file", {"path": "main.py"}, project_dir)
        assert "def hello():" in result

    def test_execute_read_nonexistent(self, sample_project):
        from spark.actions.code_generator import _execute_tool

        pid, project_dir = sample_project
        result = _execute_tool("read_file", {"path": "nope.py"}, project_dir)
        assert "Error" in result

    def test_execute_write_file(self, sample_project):
        from spark.actions.code_generator import _execute_tool

        pid, project_dir = sample_project
        result = _execute_tool(
            "write_file",
            {"path": "new_file.py", "content": "print('new')"},
            project_dir,
        )
        assert "Successfully" in result
        assert (project_dir / "new_file.py").read_text() == "print('new')"

    def test_execute_write_nested(self, sample_project):
        from spark.actions.code_generator import _execute_tool

        pid, project_dir = sample_project
        result = _execute_tool(
            "write_file",
            {"path": "src/utils/helpers.py", "content": "# helpers"},
            project_dir,
        )
        assert "Successfully" in result
        assert (project_dir / "src" / "utils" / "helpers.py").exists()

    def test_execute_list_directory(self, sample_project):
        from spark.actions.code_generator import _execute_tool

        pid, project_dir = sample_project
        result = _execute_tool("list_directory", {"path": "."}, project_dir)
        assert "main.py" in result
        assert "README.md" in result

    def test_path_traversal_blocked(self, sample_project):
        from spark.actions.code_generator import _execute_tool

        pid, project_dir = sample_project
        result = _execute_tool("read_file", {"path": "../../etc/passwd"}, project_dir)
        assert "Error" in result or "traversal" in result.lower()


# ── Git Operations Tests ──


class TestGitOps:
    def test_create_branch(self, sample_project):
        from spark.actions.github_ops import create_branch

        pid, project_dir = sample_project
        result = create_branch(str(project_dir), "spark/test-feature")
        assert result.success is True
        assert result.details["branch"] == "spark/test-feature"

        repo = Repo(project_dir)
        assert repo.active_branch.name == "spark/test-feature"

    def test_create_duplicate_branch(self, sample_project):
        from spark.actions.github_ops import create_branch

        pid, project_dir = sample_project
        create_branch(str(project_dir), "spark/test")
        result = create_branch(str(project_dir), "spark/test")
        assert result.success is False
        assert "already exists" in result.message

    def test_commit_changes(self, sample_project):
        from spark.actions.github_ops import commit_changes

        pid, project_dir = sample_project
        # Make a change
        (project_dir / "new.py").write_text("# new file\n")

        result = commit_changes(str(project_dir), "Add new file", ["new.py"])
        assert result.success is True
        assert "new.py" in result.details.get("files_changed", [])

    def test_commit_no_changes(self, sample_project):
        from spark.actions.github_ops import commit_changes

        pid, project_dir = sample_project
        result = commit_changes(str(project_dir), "Nothing changed")
        assert result.success is False

    def test_switch_back(self, sample_project):
        from spark.actions.github_ops import create_branch, switch_back

        pid, project_dir = sample_project
        repo = Repo(project_dir)
        original = repo.active_branch.name

        create_branch(str(project_dir), "spark/temp")
        assert repo.active_branch.name == "spark/temp"

        result = switch_back(str(project_dir), original)
        assert result.success is True
        assert repo.active_branch.name == original


# ── Authorization Tests ──


class TestAuthorization:
    def test_suggest_level_needs_approval(self):
        from spark.actions.authorization import needs_approval
        from spark.config import AgencyLevel

        assert needs_approval(AgencyLevel.SUGGEST, TaskType.CODE_GEN.value) is True
        assert needs_approval(AgencyLevel.SUGGEST, TaskType.RESEARCH.value) is True
        assert needs_approval(AgencyLevel.SUGGEST, TaskType.PR.value) is True

    def test_light_level_partial_approval(self):
        from spark.actions.authorization import needs_approval
        from spark.config import AgencyLevel

        assert needs_approval(AgencyLevel.LIGHT, TaskType.CODE_GEN.value) is False
        assert needs_approval(AgencyLevel.LIGHT, TaskType.RESEARCH.value) is False
        assert needs_approval(AgencyLevel.LIGHT, TaskType.PR.value) is True

    def test_full_level_no_approval(self):
        from spark.actions.authorization import needs_approval
        from spark.config import AgencyLevel

        assert needs_approval(AgencyLevel.FULL, TaskType.CODE_GEN.value) is False
        assert needs_approval(AgencyLevel.FULL, TaskType.PR.value) is False
        assert needs_approval(AgencyLevel.FULL, TaskType.RESEARCH.value) is False

    def test_propose_and_approve(self, db):
        from spark.actions.authorization import (
            _pending_proposals,
            approve_latest,
            get_pending_proposals,
            propose_action,
            ProposalStatus,
        )
        _pending_proposals.clear()

        with get_session() as session:
            project = Project(
                name="test", local_path="/tmp/test",
                status=ProjectStatus.ACTIVE.value,
            )
            session.add(project)
            session.flush()
            pid = project.id

        proposal = propose_action(pid, "test", TaskType.CODE_GEN.value, "Add auth")
        assert len(get_pending_proposals()) == 1

        approved = approve_latest()
        assert approved is not None
        assert approved.status == ProposalStatus.APPROVED
        assert len(get_pending_proposals()) == 0

        _pending_proposals.clear()

    def test_propose_and_reject(self, db):
        from spark.actions.authorization import (
            _pending_proposals,
            get_pending_proposals,
            reject_latest,
            propose_action,
            ProposalStatus,
        )
        _pending_proposals.clear()

        with get_session() as session:
            project = Project(
                name="test2", local_path="/tmp/test2",
                status=ProjectStatus.ACTIVE.value,
            )
            session.add(project)
            session.flush()
            pid = project.id

        propose_action(pid, "test2", TaskType.CODE_GEN.value, "Add tests")
        rejected = reject_latest()
        assert rejected is not None
        assert rejected.status == ProposalStatus.REJECTED
        assert len(get_pending_proposals()) == 0

        _pending_proposals.clear()

    def test_format_proposal_message(self, db):
        from spark.actions.authorization import (
            _pending_proposals,
            format_proposal_message,
            propose_action,
        )
        _pending_proposals.clear()

        with get_session() as session:
            project = Project(
                name="myapp", local_path="/tmp/myapp",
                status=ProjectStatus.ACTIVE.value,
            )
            session.add(project)
            session.flush()
            pid = project.id

        proposal = propose_action(pid, "myapp", TaskType.CODE_GEN.value, "Add error handling")
        msg = format_proposal_message(proposal)
        assert "myapp" in msg
        assert "error handling" in msg
        assert "go" in msg.lower()

        _pending_proposals.clear()
