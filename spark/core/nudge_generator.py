"""Generate context-aware nudges using Claude."""

from __future__ import annotations

import json
import logging
from datetime import datetime

import anthropic

from spark.core.context_engine import build_cross_project_context, build_project_context
from spark.knowledge.connector import get_knowledge_context_for_project
from spark.core.prompts.system import (
    NUDGE_PROMPT_TEMPLATE,
    REPLY_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
)
from spark.core.stall_detector import StallResult
from spark.db.connection import get_session
from spark.db.models import Message, MessageDirection, MessageType

logger = logging.getLogger(__name__)


def _format_recent_activity(context: dict) -> str:
    """Format recent activity events for the prompt."""
    events = context.get("recent_events", [])
    if not events:
        return "No recent activity recorded."

    lines = []
    for e in events[:10]:
        data = e.get("data", {})
        if e["type"] == "commit":
            lines.append(f"- Commit {data.get('hash', '?')}: {data.get('message', '?')}")
        elif e["type"] == "file_change":
            lines.append(f"- File {data.get('action', 'changed')}: {data.get('file', '?')}")
    return "\n".join(lines) or "No recent activity."


def _format_current_state(context: dict) -> str:
    """Format git state for the prompt."""
    git = context.get("git", {})
    if not git:
        return "No git information available."

    lines = []
    if git.get("active_branch"):
        lines.append(f"Branch: {git['active_branch']}")
    if git.get("is_dirty"):
        lines.append("Has uncommitted changes:")
        if git.get("unstaged_summary"):
            lines.append(git["unstaged_summary"][:500])
    if git.get("stale_branches"):
        branches = git["stale_branches"]
        lines.append(f"Stale branches: {', '.join(b['name'] for b in branches)}")

    commits = git.get("recent_commits", [])
    if commits:
        lines.append("\nRecent commits:")
        for c in commits[:5]:
            files_str = ", ".join(c.get("files", [])[:3])
            lines.append(f"  {c['hash']} - {c['message']} [{files_str}]")

    return "\n".join(lines) or "No git state available."


def _format_key_files(context: dict) -> str:
    """Format key file contents for the prompt."""
    key_files = context.get("key_files", {})
    if not key_files:
        return "No key files found."

    sections = []
    for name, content in key_files.items():
        sections.append(f"--- {name} ---\n{content[:1000]}")
    return "\n\n".join(sections)


def _format_previous_messages(context: dict) -> str:
    """Format previous messages so the LLM doesn't repeat itself."""
    messages = context.get("recent_messages", [])
    if not messages:
        return "No previous messages."

    lines = []
    for m in messages[:5]:
        prefix = "You" if m["direction"] == "outbound" else "Them"
        lines.append(f"{prefix}: {m['content'][:200]}")
    return "\n".join(lines)


def generate_nudge(
    stall: StallResult,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
    agency_level: str = "suggest",
) -> str | None:
    """Generate a nudge message for a stalled project.

    Returns the message text, or None if generation fails.
    """
    context = build_project_context(stall.project_id)
    if not context:
        logger.warning(f"No context available for project {stall.project_id}")
        return None

    # Cross-project context
    cross_projects = build_cross_project_context()
    other_projects = [p for p in cross_projects if p["name"] != context["project_name"]]

    cross_section = ""
    if other_projects:
        cross_section = "OTHER PROJECTS (for cross-pollination ideas):\n"
        for p in other_projects:
            status_note = f" ({p['hours_since_activity']:.0f}h since activity)" if p.get("hours_since_activity") else ""
            cross_section += f"- {p['name']}: {p['description']}{status_note}\n"

    # Build the prompt
    prompt = NUDGE_PROMPT_TEMPLATE.format(
        project_name=context["project_name"],
        description=context.get("description", ""),
        current_goal=context.get("current_goal", ""),
        recent_activity=_format_recent_activity(context),
        current_state=_format_current_state(context),
        file_tree=context.get("file_tree", "Not available")[:2000],
        key_files=_format_key_files(context),
        cross_project_section=cross_section,
        knowledge_section=get_knowledge_context_for_project(stall.project_id),
        previous_messages=_format_previous_messages(context),
        hours_since_activity=stall.hours_since_activity,
        baseline_gap=stall.baseline_gap,
    )

    # Add agency-level context if user has elevated permissions
    if agency_level in ("light", "full"):
        from spark.core.prompts.system import CONTRIBUTION_NUDGE_ADDENDUM
        prompt += "\n\n" + CONTRIBUTION_NUDGE_ADDENDUM.format(agency_level=agency_level)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        nudge_text = response.content[0].text.strip()

        # Record the outbound message
        with get_session() as session:
            msg = Message(
                project_id=stall.project_id,
                direction=MessageDirection.OUTBOUND.value,
                content=nudge_text,
                message_type=MessageType.NUDGE.value,
                context_used={"stall_confidence": stall.confidence},
                sent_at=datetime.utcnow(),
            )
            session.add(msg)

        logger.info(f"Generated nudge for {stall.project_name}: {nudge_text[:80]}...")
        return nudge_text

    except Exception as e:
        logger.error(f"Failed to generate nudge: {e}")
        return None


def generate_reply(
    project_id: str,
    user_message: str,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
) -> str | None:
    """Generate a reply to a user's message about a project."""
    context = build_project_context(project_id)
    if not context:
        return None

    # Build conversation history
    conversation = []
    for m in reversed(context.get("recent_messages", [])):
        prefix = "You" if m["direction"] == "outbound" else "Them"
        conversation.append(f"{prefix}: {m['content']}")

    prompt = REPLY_PROMPT_TEMPLATE.format(
        project_name=context["project_name"],
        description=context.get("description", ""),
        conversation_history="\n".join(conversation[-10:]),
        user_message=user_message,
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        reply_text = response.content[0].text.strip()

        # Record both messages
        with get_session() as session:
            inbound = Message(
                project_id=project_id,
                direction=MessageDirection.INBOUND.value,
                content=user_message,
                message_type=MessageType.REPLY.value,
                sent_at=datetime.utcnow(),
            )
            outbound = Message(
                project_id=project_id,
                direction=MessageDirection.OUTBOUND.value,
                content=reply_text,
                message_type=MessageType.REPLY.value,
                sent_at=datetime.utcnow(),
            )
            session.add(inbound)
            session.add(outbound)

        return reply_text

    except Exception as e:
        logger.error(f"Failed to generate reply: {e}")
        return None
