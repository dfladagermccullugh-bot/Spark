"""Rate-limited owner alerts for LLM failures (persisted so restarts don't re-spam)."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from spark.core.llm import LLMError

logger = logging.getLogger(__name__)

ALERT_WINDOW_SECONDS = 6 * 3600


class AlertLimiter:
    """Allow at most one alert per key (error type) per window."""

    def __init__(self, path: Path, window_seconds: float = ALERT_WINDOW_SECONDS):
        self._path = path
        self._window = window_seconds

    def _load(self) -> dict[str, float]:
        try:
            return json.loads(self._path.read_text())
        except (OSError, ValueError):
            return {}

    def should_send(self, key: str, now: float | None = None) -> bool:
        """Return True (and record it) if an alert for `key` is allowed now."""
        now = time.time() if now is None else now
        state = self._load()
        if now - state.get(key, 0.0) < self._window:
            return False
        state[key] = now
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(state))
        except OSError:
            logger.exception("Could not persist alert state to %s", self._path)
        return True


def format_alert(err: LLMError) -> str:
    return (
        f"Spark: Claude call failed (model {err.model}, {err.error_type}: "
        f"{err.detail[:200]}). Nudges are paused until fixed. Run `spark doctor`."
    )
