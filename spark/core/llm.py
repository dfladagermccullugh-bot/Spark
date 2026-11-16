"""Shared LLM helper: builds requests, extracts text, and fails loudly.

Every Claude call in Spark goes through :func:`generate_text` so that:

* request parameters are valid for the current model (no temperature/top_p/top_k,
  no prefill, thinking/effort set explicitly),
* text is read by content-block type (``thinking`` blocks may come first),
* any failure (API error, refusal, empty output, truncation) raises
  :class:`LLMError` carrying the model id, stop reason, and underlying error.

Two backends exist: ``anthropic`` (API key) and ``claude-cli`` (the Claude Code CLI).
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Any

import anthropic

from spark.config import DEFAULT_MODEL, SparkSettings

logger = logging.getLogger(__name__)

# Extra output budget when the model may think up-front (max_tokens covers thinking + text).
ADAPTIVE_THINKING_HEADROOM = 4000
CLI_TIMEOUT_SECONDS = 180


class LLMError(RuntimeError):
    """A Claude call failed. Carries enough detail to diagnose without a debugger."""

    def __init__(
        self,
        message: str,
        *,
        model: str,
        stop_reason: str | None = None,
        error_type: str | None = None,
    ):
        self.model = model
        self.stop_reason = stop_reason
        self.error_type = error_type or "LLMError"
        self.detail = message
        super().__init__(
            f"{message} (model={model}, stop_reason={stop_reason}, error={self.error_type})"
        )


@dataclass
class LLMResult:
    text: str
    model: str
    stop_reason: str | None
    latency_s: float


@dataclass
class LLMConfig:
    """Process-wide LLM tuning; set once at startup via :func:`configure`."""

    effort: str = "medium"
    thinking: str = "between_tools"
    backend: str = "anthropic"


_config = LLMConfig()


def configure(settings: SparkSettings) -> None:
    """Apply effort/thinking/backend from settings."""
    global _config
    _config = LLMConfig(
        effort=settings.effort, thinking=settings.thinking, backend=settings.llm_backend
    )


def get_config() -> LLMConfig:
    return _config


def build_request_kwargs(
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int,
    system: str | None = None,
    messages: list[dict],
    tools: list[dict] | None = None,
    effort: str | None = None,
    thinking: str | None = None,
) -> dict[str, Any]:
    """Build kwargs for ``client.messages.create``.

    Deliberately never sets temperature/top_p/top_k, prefill, forced tool_choice
    or budget_tokens: all of those return 400 on current models.
    """
    effort = effort or _config.effort
    thinking = thinking or _config.thinking
    if thinking == "adaptive":
        max_tokens += ADAPTIVE_THINKING_HEADROOM
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "thinking": {"type": thinking},
        "output_config": {"effort": effort},
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    return kwargs


def extract_text(content: list) -> str:
    """Join all ``text`` blocks (skipping thinking / tool_use blocks)."""
    parts = []
    for block in content or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts).strip()


def check_response(response: Any, model: str) -> str:
    """Validate a Messages response and return its text, or raise LLMError."""
    stop = getattr(response, "stop_reason", None)
    if stop == "refusal":
        raise LLMError("Claude refused the request", model=model, stop_reason=stop)
    if stop == "model_context_window_exceeded":
        raise LLMError("Context window exceeded", model=model, stop_reason=stop)
    text = extract_text(response.content)
    if not text:
        if stop == "max_tokens":
            raise LLMError(
                "Output truncated before any text (max_tokens too low for thinking + text)",
                model=model,
                stop_reason=stop,
            )
        raise LLMError("Response contained no text", model=model, stop_reason=stop)
    if stop == "max_tokens":
        logger.warning("LLM output truncated at max_tokens (model=%s)", model)
    return text


def _api_error(exc: Exception, model: str) -> LLMError:
    return LLMError(
        str(exc) or exc.__class__.__name__,
        model=model,
        error_type=exc.__class__.__name__,
    )


def make_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key)


def create_message(client: Any, **kwargs) -> Any:
    """Call ``client.messages.create`` mapping any API failure to LLMError.

    ``kwargs`` come from :func:`build_request_kwargs` (and include ``model``).
    """
    try:
        return client.messages.create(**kwargs)
    except Exception as exc:  # anthropic.APIError, httpx errors, ...
        raise _api_error(exc, kwargs.get("model", "?")) from exc


def generate_text(
    prompt: str,
    *,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    system: str | None = None,
    max_tokens: int = 800,
    effort: str | None = None,
    thinking: str | None = None,
) -> LLMResult:
    """Single-turn text generation. Raises :class:`LLMError` on any failure."""
    backend = _config.backend
    started = time.monotonic()
    if backend == "claude-cli":
        text = _cli_generate(prompt, model=model, system=system, effort=effort)
        return LLMResult(text, model, "end_turn", time.monotonic() - started)

    if not api_key:
        raise LLMError(
            "No Anthropic API key configured (set SPARK_ANTHROPIC_API_KEY)",
            model=model,
            error_type="MissingAPIKey",
        )
    kwargs = build_request_kwargs(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        effort=effort,
        thinking=thinking,
    )
    response = create_message(make_client(api_key), **kwargs)
    text = check_response(response, model)
    return LLMResult(
        text, model, getattr(response, "stop_reason", None), time.monotonic() - started
    )


def _cli_generate(
    prompt: str, *, model: str, system: str | None, effort: str | None
) -> str:
    """Generate text via the Claude Code CLI (uses the owner's subscription)."""
    cmd = [
        "claude",
        "-p",
        "--model", model,
        "--output-format", "json",
        "--effort", effort or _config.effort,
        "--no-session-persistence",
        "--disable-slash-commands",
        "--tools", "",
    ]
    if system:
        cmd += ["--system-prompt", system]
    try:
        # Prompt goes via stdin: avoids argv length limits and leading-dash ambiguity.
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=CLI_TIMEOUT_SECONDS
        )
    except FileNotFoundError as exc:
        raise LLMError(
            "`claude` CLI not found on PATH", model=model, error_type="FileNotFoundError"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise LLMError(
            f"`claude` CLI timed out after {CLI_TIMEOUT_SECONDS}s",
            model=model,
            error_type="TimeoutExpired",
        ) from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        try:  # the CLI reports failures as JSON on stdout; surface just the message
            parsed = json.loads(proc.stdout)
            if isinstance(parsed, dict) and parsed.get("result"):
                err = str(parsed["result"]).strip()
        except (json.JSONDecodeError, TypeError):
            pass
        err = err[:500]
        raise LLMError(
            f"`claude` CLI exited {proc.returncode}: {err}",
            model=model,
            error_type="CLIError",
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise LLMError(
            f"Could not parse `claude` CLI JSON output: {proc.stdout[:200]!r}",
            model=model,
            error_type="JSONDecodeError",
        ) from exc
    if not isinstance(data, dict):
        raise LLMError("Unexpected `claude` CLI output shape", model=model, error_type="CLIError")

    stop = data.get("stop_reason")
    if data.get("is_error"):
        raise LLMError(
            f"`claude` CLI reported an error: {str(data.get('result', ''))[:300]}",
            model=model,
            stop_reason=stop,
            error_type="CLIError",
        )
    text = (data.get("result") or "").strip()
    if not text:
        raise LLMError("`claude` CLI returned empty text", model=model, stop_reason=stop)
    return text


def ping(api_key: str, model: str = DEFAULT_MODEL) -> LLMResult:
    """Tiny real call used by the startup check and `spark doctor --live`."""
    return generate_text(
        "Reply with the single word: ok",
        api_key=api_key,
        model=model,
        max_tokens=32,
        effort="low",
    )
