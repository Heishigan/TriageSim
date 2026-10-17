"""The interface every agent uses to talk to a model."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class Message:
    role: str           # "system" | "user" | "assistant"
    content: str

    def as_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatResult:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0


class ModelError(RuntimeError):
    """The model server could not be reached or returned an error."""


class ChatModel(Protocol):
    name: str

    def chat(self, messages: list[Message], *, temperature: float | None = None,
             seed: int | None = None, json_schema: dict[str, Any] | None = None,
             max_tokens: int | None = None) -> ChatResult:
        """Return the model's reply. With ``json_schema`` the reply must be JSON matching it."""
        ...
