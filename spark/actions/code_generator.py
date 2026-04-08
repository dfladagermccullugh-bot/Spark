"""Generate code contributions using Claude's tool-use capabilities.

This is the engine that lets Spark actually write code, stub functions,
add error handling, write tests, and draft documentation - acting like
a real co-founder who does async work on the project.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import anthropic

from spark.core.context_engine import build_project_context
from spark.db.connection import get_session
from spark.db.models import AgentTask, TaskStatus, TaskType

logger = logging.getLogger(__name__)

CODE_GEN_SYSTEM_PROMPT = """\
You are Spark, an AI co-founder working on a project. You've been asked to make \
a small contribution to keep momentum going. Write clean, production-quality code \
that fits the project's existing style and conventions.

Rules:
- Match the existing code style (indentation, naming conventions, patterns).
- Keep changes minimal and focused. Don't refactor surrounding code.
- Include brief inline comments only where logic isn't self-evident.
- If writing a new file, include necessary imports.
- If modifying existing code, output the complete file content after changes.
- Do NOT add placeholder TODOs or "implement this" comments - write real code.
"""

# Tools the code generator can use
CODE_TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file in the project",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path from project root",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file in the project (creates or overwrites)",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path from project root",
                },
                "content": {
                    "type": "string",
                    "description": "Complete file content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files in a directory",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative directory path from project root",
                }
            },
            "required": ["path"],
        },
    },
]


def _execute_tool(tool_name: str, tool_input: dict, project_path: Path) -> str:
    """Execute a tool call against the local filesystem."""
    if tool_name == "read_file":
        file_path = project_path / tool_input["path"]
        if not file_path.exists():
            return f"Error: File not found: {tool_input['path']}"
        if not str(file_path.resolve()).startswith(str(project_path.resolve())):
            return "Error: Path traversal not allowed"
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            if len(content) > 10000:
                return content[:10000] + f"\n... ({len(content) - 10000} more chars truncated)"
            return content
        except Exception as e:
            return f"Error reading file: {e}"

    elif tool_name == "write_file":
        file_path = project_path / tool_input["path"]
        if not str(file_path.resolve()).startswith(str(project_path.resolve())):
            return "Error: Path traversal not allowed"
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(tool_input["content"], encoding="utf-8")
            return f"Successfully wrote {len(tool_input['content'])} chars to {tool_input['path']}"
        except Exception as e:
            return f"Error writing file: {e}"

    elif tool_name == "list_directory":
        dir_path = project_path / tool_input["path"]
        if not dir_path.exists():
            return f"Error: Directory not found: {tool_input['path']}"
        if not str(dir_path.resolve()).startswith(str(project_path.resolve())):
            return "Error: Path traversal not allowed"
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
            lines = []
            for entry in entries[:50]:
                if entry.name.startswith("."):
                    continue
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{entry.name}{suffix}")
            return "\n".join(lines) or "(empty directory)"
        except Exception as e:
            return f"Error listing directory: {e}"

    return f"Unknown tool: {tool_name}"


class CodeGenResult:
    """Result of a code generation task."""

    def __init__(
        self,
        success: bool,
        files_changed: list[str],
        summary: str,
        task_id: str | None = None,
    ):
        self.success = success
        self.files_changed = files_changed
        self.summary = summary
        self.task_id = task_id


def generate_code(
    project_id: str,
    instruction: str,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
    max_turns: int = 10,
) -> CodeGenResult:
    """Generate code for a project using Claude's tool-use capabilities.

    Runs an agentic loop where Claude can read files, write files, and
    list directories to make changes to the project.

    Args:
        project_id: The project to work on
        instruction: What to do (e.g., "stub out the auth endpoint")
        api_key: Anthropic API key
        model: Claude model to use
        max_turns: Maximum tool-use turns before stopping

    Returns:
        CodeGenResult with success status, files changed, and summary.
    """
    context = build_project_context(project_id)
    if not context:
        return CodeGenResult(False, [], "Could not build project context")

    project_path = Path(context["local_path"])
    if not project_path.exists():
        return CodeGenResult(False, [], f"Project path not found: {project_path}")

    # Record the task
    with get_session() as session:
        task = AgentTask(
            project_id=project_id,
            task_type=TaskType.CODE_GEN.value,
            description=instruction,
            status=TaskStatus.IN_PROGRESS.value,
        )
        session.add(task)
        session.flush()
        task_id = task.id

    # Build the initial prompt with project context
    user_prompt = f"""\
PROJECT: {context['project_name']}
DESCRIPTION: {context.get('description', 'No description')}
CURRENT GOAL: {context.get('current_goal', 'No goal set')}

FILE STRUCTURE:
{context.get('file_tree', 'Not available')[:3000]}

KEY FILES:
"""
    for name, content in context.get("key_files", {}).items():
        user_prompt += f"\n--- {name} ---\n{content[:1500]}\n"

    user_prompt += f"""
TASK:
{instruction}

Use the tools to read existing files for context, then write the changes. \
Keep changes focused and minimal. Match the existing code style.\
"""

    files_changed = []
    client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": "user", "content": user_prompt}]

    for turn in range(max_turns):
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=CODE_GEN_SYSTEM_PROMPT,
            tools=CODE_TOOLS,
            messages=messages,
        )

        # Check if we're done (no more tool use)
        if response.stop_reason == "end_turn":
            # Extract final text summary
            summary = ""
            for block in response.content:
                if block.type == "text":
                    summary += block.text
            break

        # Process tool calls
        tool_results = []
        assistant_content = response.content

        for block in assistant_content:
            if block.type == "tool_use":
                result = _execute_tool(block.name, block.input, project_path)

                if block.name == "write_file" and "Successfully" in result:
                    files_changed.append(block.input["path"])

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})
    else:
        summary = "Reached maximum tool-use turns"

    success = len(files_changed) > 0

    # Update the task record
    with get_session() as session:
        task = session.query(AgentTask).filter(AgentTask.id == task_id).first()
        if task:
            task.status = TaskStatus.DONE.value if success else TaskStatus.FAILED.value
            task.result = {
                "files_changed": files_changed,
                "summary": summary[:500],
            }
            task.completed_at = datetime.utcnow()

    logger.info(
        f"Code generation {'succeeded' if success else 'failed'}: "
        f"{len(files_changed)} files changed for '{instruction[:60]}'"
    )

    return CodeGenResult(
        success=success,
        files_changed=files_changed,
        summary=summary,
        task_id=task_id,
    )
