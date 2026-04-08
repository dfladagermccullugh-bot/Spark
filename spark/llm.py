"""Unified LLM interface - supports multiple providers via LiteLLM.

Spark works with any LLM provider: Anthropic, OpenAI, Google, Groq,
Ollama, OpenRouter, and more. Just set the model string and API key.

Model string examples:
  - "claude-sonnet-4-20250514"          (Anthropic)
  - "gpt-4o"                            (OpenAI)
  - "gemini/gemini-2.5-flash"           (Google)
  - "groq/llama-3.3-70b-versatile"      (Groq)
  - "ollama/llama3.1"                   (Ollama - local)
  - "openrouter/anthropic/claude-sonnet-4" (OpenRouter)

API keys are read from standard env vars:
  ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, GROQ_API_KEY,
  OPENROUTER_API_KEY - or set via SPARK_LLM_API_KEY as a fallback.
"""

from __future__ import annotations

import logging
from typing import Any

import litellm

logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)


def completion(
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    api_base: str | None = None,
    system: str | None = None,
    max_tokens: int = 500,
    tools: list[dict] | None = None,
    **kwargs: Any,
) -> "litellm.ModelResponse":
    """Send a completion request to any supported LLM provider.

    Args:
        model: Model identifier (e.g., "gpt-4o", "claude-sonnet-4-20250514").
        messages: List of message dicts with 'role' and 'content'.
        api_key: API key override. If not set, litellm reads from env vars.
        api_base: Base URL override (useful for Ollama, custom endpoints).
        system: System prompt. Injected as the first message if provided.
        max_tokens: Maximum tokens in the response.
        tools: Tool definitions for function calling (OpenAI format).
        **kwargs: Additional args passed to litellm.completion().

    Returns:
        litellm.ModelResponse object.
    """
    # Build the full message list
    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    # Build kwargs for litellm
    call_kwargs: dict[str, Any] = {
        "model": model,
        "messages": full_messages,
        "max_tokens": max_tokens,
    }

    if api_key:
        call_kwargs["api_key"] = api_key
    if api_base:
        call_kwargs["api_base"] = api_base
    if tools:
        call_kwargs["tools"] = _convert_tools(tools)

    call_kwargs.update(kwargs)

    return litellm.completion(**call_kwargs)


def get_text(response: "litellm.ModelResponse") -> str:
    """Extract the text content from a completion response."""
    choice = response.choices[0]
    if choice.message and choice.message.content:
        return choice.message.content.strip()
    return ""


def get_tool_calls(response: "litellm.ModelResponse") -> list[dict]:
    """Extract tool calls from a completion response.

    Returns list of dicts: {id, name, arguments} where arguments
    is already parsed from JSON.
    """
    import json

    choice = response.choices[0]
    if not choice.message or not choice.message.tool_calls:
        return []

    calls = []
    for tc in choice.message.tool_calls:
        try:
            args = json.loads(tc.function.arguments)
        except (json.JSONDecodeError, TypeError):
            args = {}
        calls.append({
            "id": tc.id,
            "name": tc.function.name,
            "arguments": args,
        })
    return calls


def has_tool_calls(response: "litellm.ModelResponse") -> bool:
    """Check if the response contains tool calls."""
    choice = response.choices[0]
    return bool(choice.message and choice.message.tool_calls)


def is_done(response: "litellm.ModelResponse") -> bool:
    """Check if the model is done (no more tool calls)."""
    return not has_tool_calls(response)


def build_tool_result_messages(
    response: "litellm.ModelResponse",
    results: dict[str, str],
) -> list[dict]:
    """Build the message pair for continuing a tool-use conversation.

    Args:
        response: The response containing tool calls.
        results: Dict mapping tool call ID to result string.

    Returns:
        List of two messages: [assistant_message, tool_results_message].
    """
    # The assistant's message (with tool calls) must be echoed back
    assistant_msg = response.choices[0].message.model_dump()

    tool_messages = []
    for tool_call_id, result_content in results.items():
        tool_messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result_content,
        })

    return [assistant_msg] + tool_messages


def _convert_tools(tools: list[dict]) -> list[dict]:
    """Convert Anthropic-style tool definitions to OpenAI format if needed.

    Handles both formats:
    - OpenAI: {"type": "function", "function": {"name": ..., "parameters": ...}}
    - Anthropic: {"name": ..., "input_schema": ...}
    """
    converted = []
    for tool in tools:
        if "type" in tool and tool["type"] == "function":
            # Already OpenAI format
            converted.append(tool)
        elif "input_schema" in tool:
            # Anthropic format -> OpenAI format
            converted.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"],
                },
            })
        else:
            converted.append(tool)
    return converted


def supports_tools(model: str) -> bool:
    """Check if a model likely supports tool/function calling.

    Most major models do, but some small local models may not.
    """
    no_tool_patterns = ["ollama/tinyllama", "ollama/phi"]
    model_lower = model.lower()
    for pattern in no_tool_patterns:
        if pattern in model_lower:
            return False
    return True
