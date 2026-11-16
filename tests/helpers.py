"""Shared fakes for offline LLM tests."""

from types import SimpleNamespace


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def thinking_block(text="hmm"):
    return SimpleNamespace(type="thinking", thinking=text, signature="sig")


def tool_block(name, input, id="tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=input, id=id)


def response(content, stop_reason="end_turn"):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class FakeClient:
    """Mimics anthropic.Anthropic; returns/raises queued items from messages.create."""

    def __init__(self, *items):
        self.items = list(items)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, Exception):
            raise item
        return item
