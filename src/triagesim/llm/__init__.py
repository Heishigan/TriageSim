"""Model layer: one small chat interface, implemented for Ollama (and a fake for tests)."""
from .base import ChatModel, ChatResult, Message

__all__ = ["ChatModel", "ChatResult", "Message"]
