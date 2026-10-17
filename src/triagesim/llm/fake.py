"""A scripted model for tests and demos: no server, fully predictable."""
from __future__ import annotations

from typing import Callable

from .base import ChatResult, Message

Responder = Callable[[list[Message]], str]


class FakeModel:
    """Replies from a list (in order, repeating the last) or from a function of the messages."""

    def __init__(self, name: str = "fake", replies: list[str] | Responder | None = None):
        self.name = name
        self.replies = replies or ["OK"]
        self.calls: list[list[Message]] = []

    def chat(self, messages, *, temperature=None, seed=None, json_schema=None, max_tokens=None) -> ChatResult:
        self.calls.append(list(messages))
        if callable(self.replies):
            text = self.replies(messages)
        else:
            text = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return ChatResult(content=text, model=self.name, prompt_tokens=10, completion_tokens=5)
