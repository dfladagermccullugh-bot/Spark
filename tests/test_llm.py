"""Tests for the shared LLM helper (offline: anthropic client and subprocess are mocked)."""

import json
import subprocess

import anthropic
import httpx
import pytest

from spark.config import DEFAULT_MODEL
from spark.core import llm
from spark.core.llm import LLMError
from tests.helpers import FakeClient, response, text_block, thinking_block


def _patch_client(monkeypatch, client):
    monkeypatch.setattr(llm, "make_client", lambda api_key: client)


def _not_found():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.NotFoundError(
        "model: claude-gone", response=httpx.Response(404, request=req), body=None
    )


def test_thinking_block_before_text_is_parsed(monkeypatch):
    client = FakeClient(response([thinking_block(), text_block("  hello there ")]))
    _patch_client(monkeypatch, client)
    result = llm.generate_text("hi", api_key="k", model=DEFAULT_MODEL)
    assert result.text == "hello there"
    assert result.stop_reason == "end_turn"


def test_request_kwargs_have_thinking_effort_and_no_sampling_params(monkeypatch):
    client = FakeClient(response([text_block("ok")]))
    _patch_client(monkeypatch, client)
    llm.generate_text("hi", api_key="k", model="m", system="sys", max_tokens=123)
    kw = client.calls[0]
    assert kw["thinking"] == {"type": "between_tools"}
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["max_tokens"] == 123
    assert kw["system"] == "sys"
    for banned in ("temperature", "top_p", "top_k", "tool_choice", "budget_tokens"):
        assert banned not in kw
    assert kw["messages"][-1]["role"] == "user"  # no assistant prefill


def test_adaptive_thinking_adds_token_headroom():
    kw = llm.build_request_kwargs(
        model="m", max_tokens=500, messages=[], thinking="adaptive", effort="high"
    )
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "high"}
    assert kw["max_tokens"] == 500 + llm.ADAPTIVE_THINKING_HEADROOM


@pytest.mark.parametrize(
    "resp,stop",
    [
        (response([], "refusal"), "refusal"),
        (response([thinking_block()], "end_turn"), "end_turn"),  # no text
        (response([text_block("  ")], "end_turn"), "end_turn"),  # empty text
        (response([thinking_block()], "max_tokens"), "max_tokens"),  # truncated, no text
        (response([text_block("x")], "model_context_window_exceeded"),
         "model_context_window_exceeded"),
    ],
)
def test_bad_responses_raise_llm_error(monkeypatch, resp, stop):
    _patch_client(monkeypatch, FakeClient(resp))
    with pytest.raises(LLMError) as ei:
        llm.generate_text("hi", api_key="k", model="the-model")
    assert ei.value.stop_reason == stop
    assert ei.value.model == "the-model"
    assert "the-model" in str(ei.value)


def test_truncated_but_nonempty_text_is_returned(monkeypatch):
    _patch_client(monkeypatch, FakeClient(response([text_block("partial")], "max_tokens")))
    assert llm.generate_text("hi", api_key="k").text == "partial"


def test_api_error_becomes_llm_error(monkeypatch):
    _patch_client(monkeypatch, FakeClient(_not_found()))
    with pytest.raises(LLMError) as ei:
        llm.generate_text("hi", api_key="k", model="claude-gone")
    assert ei.value.error_type == "NotFoundError"
    assert ei.value.model == "claude-gone"
    assert isinstance(ei.value.__cause__, anthropic.NotFoundError)


def test_missing_api_key_raises():
    with pytest.raises(LLMError) as ei:
        llm.generate_text("hi", api_key="")
    assert ei.value.error_type == "MissingAPIKey"


# ---- claude-cli backend -------------------------------------------------


def _cli_config():
    llm._config = llm.LLMConfig(backend="claude-cli")


def test_cli_backend_parses_json(monkeypatch):
    _cli_config()
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        out = json.dumps({"type": "result", "is_error": False, "result": " nudge! "})
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    result = llm.generate_text("the prompt", model="m", system="sys")
    assert result.text == "nudge!"
    cmd = seen["cmd"]
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--model") + 1] == "m"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--system-prompt") + 1] == "sys"
    assert seen["kwargs"]["input"] == "the prompt"


def test_cli_backend_nonzero_exit_raises(monkeypatch):
    _cli_config()
    monkeypatch.setattr(
        llm.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not logged in"),
    )
    with pytest.raises(LLMError, match="not logged in") as ei:
        llm.generate_text("p", model="m")
    assert ei.value.error_type == "CLIError"


@pytest.mark.parametrize(
    "stdout",
    ["not json", json.dumps({"is_error": True, "result": "boom"}), json.dumps({"result": ""})],
)
def test_cli_backend_bad_output_raises(monkeypatch, stdout):
    _cli_config()
    monkeypatch.setattr(
        llm.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr=""),
    )
    with pytest.raises(LLMError):
        llm.generate_text("p", model="m")


def test_cli_backend_missing_binary_raises(monkeypatch):
    _cli_config()

    def boom(cmd, **kw):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(llm.subprocess, "run", boom)
    with pytest.raises(LLMError, match="not found"):
        llm.generate_text("p", model="m")


def test_cli_backend_never_touches_anthropic_client(monkeypatch):
    _cli_config()
    monkeypatch.setattr(llm, "make_client", lambda k: pytest.fail("API client used"))
    monkeypatch.setattr(
        llm.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"result": "ok"}), stderr=""
        ),
    )
    assert llm.generate_text("p", model="m").text == "ok"


def test_call_sites_surface_llm_error(monkeypatch):
    """A representative call site (memory extraction) raises instead of returning []."""
    from spark.core.memory import extract_memories

    _patch_client(monkeypatch, FakeClient(_not_found()))
    with pytest.raises(LLMError):
        extract_memories([{"direction": "inbound", "content": "x"}], "k", "m")


def test_extract_memories_with_thinking_block(monkeypatch):
    from spark.core.memory import extract_memories

    payload = json.dumps([{"type": "goal", "content": "ship billing"}])
    _patch_client(monkeypatch, FakeClient(response([thinking_block(), text_block(payload)])))
    out = extract_memories([{"direction": "inbound", "content": "x"}], "k", "m")
    assert out == [{"type": "goal", "content": "ship billing"}]


def test_ping_returns_result(monkeypatch):
    _patch_client(monkeypatch, FakeClient(response([text_block("ok")])))
    r = llm.ping("k", "m")
    assert (r.text, r.model, r.stop_reason) == ("ok", "m", "end_turn")


def test_cli_nonzero_exit_surfaces_json_result_message(monkeypatch):
    _cli_config()
    out = json.dumps({"is_error": True, "result": "Not logged in", "usage": {"x": 1}})
    monkeypatch.setattr(
        llm.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout=out, stderr=""),
    )
    with pytest.raises(LLMError) as ei:
        llm.generate_text("p", model="m")
    assert "Not logged in" in str(ei.value) and "usage" not in str(ei.value)
