"""Research capabilities: search the knowledge base, analyze code, summarize findings.

When a project is stuck, Spark can research the blocker - searching the user's
knowledge base, analyzing error patterns in code, and summarizing findings.
"""

from __future__ import annotations

import logging
from datetime import datetime

import anthropic

from spark.core.context_engine import build_project_context
from spark.db.connection import get_session
from spark.db.models import AgentTask, TaskStatus, TaskType
from spark.knowledge.indexer import search_knowledge, search_project_files

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM_PROMPT = """\
You are Spark, an AI co-founder doing research for a project. You've been asked \
to investigate something - could be a technical question, a blocker analysis, \
finding relevant resources, or exploring approaches to a problem.

Be thorough but concise. Organize findings clearly. If you find relevant code \
patterns or knowledge items, explain how they apply to the current situation. \
End with a concrete recommendation.\
"""


class ResearchResult:
    """Result of a research task."""

    def __init__(
        self,
        success: bool,
        summary: str,
        findings: list[dict] | None = None,
        recommendation: str = "",
        task_id: str | None = None,
    ):
        self.success = success
        self.summary = summary
        self.findings = findings or []
        self.recommendation = recommendation
        self.task_id = task_id


def research_topic(
    project_id: str,
    question: str,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
) -> ResearchResult:
    """Research a question in the context of a project.

    Searches the knowledge base and project files for relevant information,
    then uses Claude to synthesize a useful answer.
    """
    context = build_project_context(project_id)
    if not context:
        return ResearchResult(False, "Could not build project context")

    # Record the task
    with get_session() as session:
        task = AgentTask(
            project_id=project_id,
            task_type=TaskType.RESEARCH.value,
            description=question,
            status=TaskStatus.IN_PROGRESS.value,
        )
        session.add(task)
        session.flush()
        task_id = task.id

    # Search knowledge base
    knowledge_results = search_knowledge(question, n_results=5)
    project_file_results = search_project_files(question, project_id=project_id, n_results=5)

    # Also search across other projects for cross-pollination
    cross_project_results = search_project_files(question, n_results=5)

    # Build research context
    research_context = f"""\
PROJECT: {context['project_name']}
DESCRIPTION: {context.get('description', 'No description')}
CURRENT GOAL: {context.get('current_goal', 'No goal set')}

RESEARCH QUESTION:
{question}

RELEVANT KNOWLEDGE ITEMS:
"""
    if knowledge_results:
        for kr in knowledge_results:
            dist = f" (relevance: {1.0 - (kr.get('distance', 1.0) / 2.0):.0%})" if kr.get("distance") is not None else ""
            research_context += f"\n- {kr['title']}{dist}"
            if kr.get("source_url"):
                research_context += f"\n  URL: {kr['source_url']}"
            if kr.get("content"):
                research_context += f"\n  {kr['content'][:300]}"
    else:
        research_context += "\n(No relevant knowledge items found)"

    research_context += "\n\nRELEVANT PROJECT FILES:\n"
    if project_file_results:
        for pf in project_file_results:
            research_context += f"\n- {pf.get('file_path', 'unknown')}"
            if pf.get("content"):
                research_context += f"\n  {pf['content'][:300]}"
    else:
        research_context += "\n(No relevant project files found)"

    if cross_project_results:
        # Filter to only files from other projects
        other_files = [
            f for f in cross_project_results
            if f.get("project_id") != project_id
        ]
        if other_files:
            research_context += "\n\nRELATED FILES FROM OTHER PROJECTS:\n"
            for pf in other_files:
                research_context += f"\n- {pf.get('file_path', 'unknown')} (project: {pf.get('project_id', '?')})"
                if pf.get("content"):
                    research_context += f"\n  {pf['content'][:200]}"

    research_context += """

Based on the above context, provide:
1. A clear answer to the research question
2. Relevant resources or code patterns found
3. A concrete recommendation for next steps

Keep it concise - this will be sent as a message.\
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            system=RESEARCH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": research_context}],
        )

        summary = response.content[0].text.strip()

        # Build findings list
        findings = []
        for kr in knowledge_results:
            findings.append({
                "type": "knowledge",
                "title": kr["title"],
                "url": kr.get("source_url"),
                "relevance": kr.get("distance"),
            })
        for pf in project_file_results:
            findings.append({
                "type": "project_file",
                "path": pf.get("file_path"),
            })

        # Update task
        with get_session() as session:
            task = session.query(AgentTask).filter(AgentTask.id == task_id).first()
            if task:
                task.status = TaskStatus.DONE.value
                task.result = {
                    "summary": summary[:500],
                    "findings_count": len(findings),
                }
                task.completed_at = datetime.utcnow()

        return ResearchResult(
            success=True,
            summary=summary,
            findings=findings,
            task_id=task_id,
        )

    except Exception as e:
        logger.error(f"Research failed: {e}")
        with get_session() as session:
            task = session.query(AgentTask).filter(AgentTask.id == task_id).first()
            if task:
                task.status = TaskStatus.FAILED.value
                task.completed_at = datetime.utcnow()

        return ResearchResult(False, f"Research failed: {e}", task_id=task_id)


def analyze_blocker(
    project_id: str,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
) -> ResearchResult:
    """Proactively analyze what might be blocking progress on a project.

    Looks at unstaged changes, recent commit patterns, and stale branches
    to identify potential blockers and suggest solutions.
    """
    context = build_project_context(project_id)
    if not context:
        return ResearchResult(False, "Could not build project context")

    git_ctx = context.get("git", {})
    blocker_signals = []

    # Check for uncommitted work (might be stuck mid-change)
    if git_ctx.get("is_dirty"):
        blocker_signals.append(
            f"Uncommitted changes on branch '{git_ctx.get('active_branch', 'unknown')}':\n"
            f"{git_ctx.get('unstaged_summary', 'unknown changes')}"
        )

    # Check for stale branches (abandoned work?)
    stale = git_ctx.get("stale_branches", [])
    if stale:
        for b in stale:
            blocker_signals.append(
                f"Stale branch '{b['name']}' ({b['days_stale']} days): {b['last_message']}"
            )

    # Look at recent commit messages for "WIP", "TODO", "fix", "broken"
    recent_commits = git_ctx.get("recent_commits", [])
    problem_commits = []
    for c in recent_commits[:5]:
        msg = c.get("message", "").lower()
        if any(word in msg for word in ["wip", "todo", "fix", "broken", "hack", "temp"]):
            problem_commits.append(f"{c['hash']}: {c['message']}")

    if problem_commits:
        blocker_signals.append(
            "Recent commits suggest work-in-progress:\n" +
            "\n".join(f"  {c}" for c in problem_commits)
        )

    if not blocker_signals:
        return ResearchResult(
            True,
            "No obvious blockers detected. The project looks clean.",
            recommendation="Consider setting a new goal or picking up a feature from the backlog.",
        )

    question = (
        "Analyze these potential blockers and suggest how to unblock progress:\n\n" +
        "\n\n".join(blocker_signals)
    )

    return research_topic(project_id, question, api_key, model)
