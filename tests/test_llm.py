"""Model layer against a mock Ollama server (no real server needed)."""
import json

import httpx
import pytest

from triagesim.experiment.config import ModelSettings
from triagesim.llm.base import Message, ModelError
from triagesim.llm.fake import FakeModel
from triagesim.llm.ollama import OllamaClient, download_from_huggingface, ensure_model


class MockOllama:
    def __init__(self, installed=("qwen2.5:32b",)):
        self.installed = list(installed)
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n, "size": 1} for n in self.installed]})
        if path == "/api/chat":
            body = json.loads(request.content)
            return httpx.Response(200, json={"message": {"content": f" reply from {body['model']} "},
                                             "prompt_eval_count": 12, "eval_count": 3})
        if path == "/api/pull":
            name = json.loads(request.content)["model"]
            if name == "missing:1b":
                return httpx.Response(200, content=b'{"error":"file does not exist"}\n')
            self.installed.append(name)
            lines = [{"status": "pulling manifest"}, {"status": "downloading", "completed": 50, "total": 100},
                     {"status": "success"}]
            return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())
        return httpx.Response(404)


def client(mock):
    return OllamaClient(transport=httpx.MockTransport(mock))


def test_chat_sends_options_and_schema():
    mock = MockOllama()
    result = client(mock).chat("qwen2.5:32b", [Message("user", "hi")], temperature=0.0, seed=42,
                               json_schema={"type": "object"})
    body = json.loads(mock.requests[-1].content)
    assert body["options"] == {"temperature": 0.0, "seed": 42} and body["format"] == {"type": "object"}
    assert result.content == "reply from qwen2.5:32b" and result.prompt_tokens == 12


def test_pull_reports_progress_and_errors():
    mock, seen = MockOllama(), []
    c = client(mock)
    c.pull("llama3.1:8b", seen.append)
    assert seen[1] == {"status": "downloading", "completed": 50, "total": 100}
    assert c.has_model("llama3.1:8b")
    with pytest.raises(ModelError, match="file does not exist"):
        c.pull("missing:1b")


def test_unreachable_server_gives_plain_error():
    def down(request):
        raise httpx.ConnectError("refused")
    with pytest.raises(ModelError, match="not reachable"):
        OllamaClient(transport=httpx.MockTransport(down)).list_models()


def test_ensure_model_pulls_only_when_missing(tmp_path):
    mock = MockOllama()
    c = client(mock)
    assert ensure_model(c, ModelSettings(name="qwen2.5:32b"), None, tmp_path) == "already installed"
    assert ensure_model(c, ModelSettings(name="llama3.1:8b"), None, tmp_path) == "downloaded from the Ollama library"
    assert ensure_model(c, ModelSettings(name="x", source="fake"), None, tmp_path).startswith("fake")


def test_huggingface_download_uses_token_and_reports_refusal(tmp_path):
    seen_auth = []

    def hf(request):
        seen_auth.append(request.headers.get("authorization"))
        if "gated" in request.url.path:
            return httpx.Response(403)
        return httpx.Response(200, content=b"GGUF" * 10, headers={"content-length": "40"})

    http = httpx.Client(transport=httpx.MockTransport(hf))
    path = download_from_huggingface("org/model", "m.gguf", "hf_secret", tmp_path, client=http)
    assert path.read_bytes() == b"GGUF" * 10 and seen_auth == ["Bearer hf_secret"]
    with pytest.raises(ModelError, match="licence"):
        download_from_huggingface("org/gated", "m.gguf", "hf_secret", tmp_path, client=http)


def test_fake_model_replies_in_order():
    m = FakeModel(replies=["a", "b"])
    assert [m.chat([]).content for _ in range(3)] == ["a", "b", "b"]
