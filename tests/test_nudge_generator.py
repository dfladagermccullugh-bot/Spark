"""Tests for nudge generation (prompt formatting, not LLM calls)."""

from datetime import datetime, timedelta

import pytest

from spark.core.nudge_generator import (
    _format_current_state,
    _format_key_files,
    _format_previous_messages,
    _format_recent_activity,
)


class TestFormatRecentActivity:
    def test_formats_commits(self):
        context = {
            "recent_events": [
                {
                    "type": "commit",
                    "data": {"hash": "abc123", "message": "Add auth module"},
                    "at": "2025-01-01T10:00:00",
                },
                {
                    "type": "file_change",
                    "data": {"file": "src/main.py", "action": "modified"},
                    "at": "2025-01-01T11:00:00",
                },
            ]
        }
        result = _format_recent_activity(context)
        assert "abc123" in result
        assert "Add auth module" in result
        assert "src/main.py" in result

    def test_handles_empty_events(self):
        result = _format_recent_activity({"recent_events": []})
        assert "No recent activity" in result

    def test_handles_missing_events(self):
        result = _format_recent_activity({})
        assert "No recent activity" in result


class TestFormatCurrentState:
    def test_formats_git_state(self):
        context = {
            "git": {
                "active_branch": "feature/auth",
                "is_dirty": True,
                "unstaged_summary": " 3 files changed, 42 insertions(+)",
                "recent_commits": [
                    {
                        "hash": "abc123",
                        "message": "WIP auth",
                        "author": "dev",
                        "date": "2025-01-01 10:00",
                        "files": ["auth.py", "config.py"],
                    }
                ],
                "stale_branches": [
                    {"name": "old-feature", "days_stale": 30, "last_message": "Started feature"},
                ],
            }
        }
        result = _format_current_state(context)
        assert "feature/auth" in result
        assert "uncommitted" in result.lower()
        assert "abc123" in result
        assert "old-feature" in result

    def test_handles_no_git(self):
        result = _format_current_state({})
        assert "No git" in result


class TestFormatKeyFiles:
    def test_formats_files(self):
        context = {
            "key_files": {
                "README.md": "# My Project\nA cool project.",
                "pyproject.toml": "[project]\nname = 'cool'",
            }
        }
        result = _format_key_files(context)
        assert "README.md" in result
        assert "My Project" in result
        assert "pyproject.toml" in result

    def test_handles_no_files(self):
        result = _format_key_files({})
        assert "No key files" in result


class TestFormatPreviousMessages:
    def test_formats_conversation(self):
        context = {
            "recent_messages": [
                {"direction": "outbound", "content": "Hey, what about adding caching?"},
                {"direction": "inbound", "content": "Good idea, let me think about it"},
            ]
        }
        result = _format_previous_messages(context)
        assert "You:" in result
        assert "Them:" in result
        assert "caching" in result

    def test_handles_no_messages(self):
        result = _format_previous_messages({})
        assert "No previous" in result
