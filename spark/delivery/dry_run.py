"""Dry-run delivery: print messages and append them to a file instead of sending."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from spark.delivery.base import DeliveryAdapter

logger = logging.getLogger(__name__)


class DryRunAdapter(DeliveryAdapter):
    """Writes outgoing messages to stdout and `path`; never touches the network."""

    def __init__(self, path: Path):
        self._path = path

    async def send(self, message: str) -> bool:
        stamp = datetime.now().isoformat(timespec="seconds")
        print(f"[spark dry-run {stamp}] {message}", flush=True)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(f"[{stamp}] {message}\n\n")
        except OSError:
            logger.exception("Dry-run: could not write to %s", self._path)
            return False
        logger.info("Dry-run message recorded (not sent): %s...", message[:60])
        return True

    async def start_listening(self, on_message: Callable[[str], str | None]) -> None:
        logger.info("Dry-run delivery: not listening for incoming messages")

    async def stop(self) -> None:
        return None
