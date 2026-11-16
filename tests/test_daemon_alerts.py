"""Daemon failure path: LLM errors are logged, alerted once (rate-limited), never silent."""

import asyncio
import logging
import time

import anthropic
import httpx

from spark.config import SparkSettings
from spark.core import llm
from spark.core.alerts import AlertLimiter, format_alert
from spark.core.llm import LLMError
from spark.daemon import SparkDaemon
from tests.helpers import FakeClient


class FakeDelivery:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)
        return True


def _not_found():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.NotFoundError(
        "model: nope", response=httpx.Response(404, request=req), body=None
    )


def _daemon(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = SparkSettings(
        _env_file=None, data_dir=tmp_path / "data", anthropic_api_key="k",
        projects_dir=tmp_path / "p", knowledge_dir=tmp_path / "k",
    )
    d = SparkDaemon(settings)
    d._delivery = FakeDelivery()
    return d


async def test_not_found_triggers_exactly_one_alert(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(llm, "make_client", lambda k: FakeClient(_not_found()))
    d = _daemon(tmp_path, monkeypatch)
    d._loop = asyncio.get_running_loop()

    monkeypatch.setattr("spark.daemon.detect_stalls", lambda **kw: [object()])

    def failing_nudge(stall, api_key, model, agency_level):
        return llm.generate_text("x", api_key=api_key, model=model)

    monkeypatch.setattr("spark.daemon.generate_nudge", failing_nudge)

    with caplog.at_level(logging.ERROR):
        # scheduler jobs run in worker threads; mirror that
        await asyncio.to_thread(d._check_stalls)
        await asyncio.to_thread(d._check_stalls)
        await asyncio.sleep(0.05)

    assert len(d._delivery.sent) == 1
    msg = d._delivery.sent[0]
    assert d.settings.model in msg and "NotFoundError" in msg and "spark doctor" in msg
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) >= 2 and all(d.settings.model in r.getMessage() for r in errors[:2])


async def test_startup_check_retired_model_logs_and_alerts(tmp_path, monkeypatch, caplog):
    d = _daemon(tmp_path, monkeypatch)
    d.settings.model = "claude-sonnet-4-20250514"
    d._loop = asyncio.get_running_loop()
    monkeypatch.setattr(llm, "ping", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    with caplog.at_level(logging.ERROR):
        ok = await asyncio.to_thread(d._startup_check)
    await asyncio.sleep(0.05)
    assert ok is False
    assert any("STARTUP CHECK FAILED" in r.getMessage() for r in caplog.records)
    assert len(d._delivery.sent) == 1 and "RetiredModel" in d._delivery.sent[0]


async def test_startup_check_auth_error_alerts_and_success_is_quiet(tmp_path, monkeypatch):
    d = _daemon(tmp_path, monkeypatch)
    d._loop = asyncio.get_running_loop()

    def bad_ping(*a, **k):
        raise LLMError("invalid x-api-key", model="m", error_type="AuthenticationError")

    monkeypatch.setattr(llm, "ping", bad_ping)
    assert await asyncio.to_thread(d._startup_check) is False
    await asyncio.sleep(0.05)
    assert len(d._delivery.sent) == 1

    (tmp_path / "other").mkdir()
    d2 = _daemon(tmp_path / "other", monkeypatch)
    monkeypatch.setattr(
        llm, "ping", lambda *a, **k: llm.LLMResult("ok", "m", "end_turn", 0.01)
    )
    assert await asyncio.to_thread(d2._startup_check) is True
    assert d2._delivery.sent == []


def test_reply_failure_returns_alert_text(tmp_path, monkeypatch):
    d = _daemon(tmp_path, monkeypatch)
    from datetime import datetime

    from spark.db.connection import get_session, init_db
    from spark.db.models import Message, MessageDirection, Project

    init_db(tmp_path / "t.db")
    with get_session() as s:
        p = Project(name="a", local_path="/tmp/a")
        s.add(p)
        s.flush()
        s.add(Message(project_id=p.id, direction=MessageDirection.OUTBOUND.value,
                      content="hi", message_type="nudge", sent_at=datetime.utcnow()))

    def boom(**kw):
        raise LLMError("gone", model="m", error_type="NotFoundError")

    monkeypatch.setattr("spark.daemon.generate_reply", boom)
    out = d._handle_incoming("hello")
    assert "Claude call failed" in out and "spark doctor" in out


def test_alert_limiter_window(tmp_path):
    lim = AlertLimiter(tmp_path / "s.json", window_seconds=100)
    t = time.time()
    assert lim.should_send("A", now=t)
    assert not lim.should_send("A", now=t + 50)
    assert lim.should_send("B", now=t + 50)  # different error type
    assert lim.should_send("A", now=t + 101)
    # persisted across instances (daemon restart)
    assert not AlertLimiter(tmp_path / "s.json", window_seconds=100).should_send("A", now=t + 102)


def test_format_alert_shape():
    msg = format_alert(LLMError("model: x", model="m1", error_type="NotFoundError"))
    assert msg.startswith("Spark: Claude call failed (model m1, NotFoundError:")
    assert "Run `spark doctor`" in msg
