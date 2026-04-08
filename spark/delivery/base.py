"""Base interface for message delivery adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class DeliveryAdapter(ABC):
    """Base class for messaging platform adapters."""

    @abstractmethod
    async def send(self, message: str) -> bool:
        """Send a message to the user. Returns True on success."""
        ...

    @abstractmethod
    async def start_listening(self, on_message: Callable[[str], str | None]) -> None:
        """Start listening for incoming messages.

        on_message receives the user's text and returns a reply (or None).
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the adapter and clean up resources."""
        ...
