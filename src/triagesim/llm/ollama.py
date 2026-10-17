"""Ollama: chat, list installed models, download models with progress.

Models come from two sources:
  * the Ollama library, e.g. ``qwen2.5:32b``  -> /api/pull
  * a GGUF file on Hugging Face (public, gated or private) -> downloaded with the
    user's HF token, uploaded to Ollama as a blob, then registered with /api/create.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx

from .base import ChatResult, Message, ModelError

DEFAULT_URL = "http://127.0.0.1:11434"
Progress = Callable[[dict], None]   # receives {"status": str, "completed": int, "total": int}


class OllamaClient:
    def __init__(self, base_url: str = DEFAULT_URL, timeout: float = 600.0,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        # Never route local model traffic through a proxy.
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport, trust_env=False)

    # ---- server ------------------------------------------------------------------
    def version(self) -> str:
        return self._get("/api/version").get("version", "?")

    def list_models(self) -> list[dict]:
        """Installed models: name, size in bytes, modified time."""
        return [{"name": m["name"], "size": m.get("size", 0), "modified": m.get("modified_at", "")}
                for m in self._get("/api/tags").get("models", [])]

    def has_model(self, name: str) -> bool:
        wanted = name if ":" in name else f"{name}:latest"
        return any(m["name"] == wanted for m in self.list_models())

    # ---- chat --------------------------------------------------------------------
    def chat(self, model: str, messages: list[Message], *, temperature: float | None = None,
             seed: int | None = None, json_schema: dict | None = None, max_tokens: int | None = None) -> ChatResult:
        payload: dict[str, Any] = {"model": model, "messages": [m.as_dict() for m in messages], "stream": False}
        options = {k: v for k, v in {"temperature": temperature, "seed": seed, "num_predict": max_tokens}.items()
                   if v is not None}
        if options:
            payload["options"] = options
        if json_schema is not None:
            payload["format"] = json_schema
        start = time.time()
        data = self._post("/api/chat", payload)
        return ChatResult(content=data.get("message", {}).get("content", "").strip(), model=model,
                          prompt_tokens=data.get("prompt_eval_count", 0),
                          completion_tokens=data.get("eval_count", 0), seconds=time.time() - start)

    def delete(self, name: str) -> None:
        """Remove an installed model from Ollama (frees its disk space)."""
        try:
            r = self._http.request("DELETE", "/api/delete", json={"model": name})
        except httpx.HTTPError as exc:
            raise ModelError(f"Ollama at {self.base_url} is not reachable ({exc}). Is it running?") from exc
        if r.status_code != 200:
            raise ModelError(f"Could not delete {name}: {r.text[:200]}")

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        return self._post("/api/embed", {"model": model, "input": texts}).get("embeddings", [])

    # ---- downloads ---------------------------------------------------------------
    def pull(self, name: str, progress: Progress | None = None) -> None:
        """Download a model from the Ollama library."""
        for event in self._stream("/api/pull", {"model": name, "stream": True}):
            if "error" in event:
                raise ModelError(f"Could not download {name}: {event['error']}")
            if progress:
                progress({"status": event.get("status", ""), "completed": event.get("completed", 0),
                          "total": event.get("total", 0)})

    def import_gguf(self, name: str, gguf: Path, progress: Progress | None = None) -> None:
        """Register a local GGUF file with Ollama under ``name``."""
        digest = "sha256:" + _sha256(gguf)
        if self._http.head(f"/api/blobs/{digest}").status_code != 200:
            if progress:
                progress({"status": "uploading to Ollama", "completed": 0, "total": gguf.stat().st_size})
            with open(gguf, "rb") as f:
                r = self._http.post(f"/api/blobs/{digest}", content=f)
            if r.status_code not in (200, 201):
                raise ModelError(f"Upload to Ollama failed: {r.text}")
        for event in self._stream("/api/create", {"model": name, "files": {gguf.name: digest}, "stream": True}):
            if "error" in event:
                raise ModelError(f"Could not register {name}: {event['error']}")
            if progress:
                progress({"status": event.get("status", ""), "completed": 0, "total": 0})

    # ---- plumbing ----------------------------------------------------------------
    def _get(self, path: str) -> dict:
        try:
            r = self._http.get(path)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as exc:
            raise ModelError(f"Ollama at {self.base_url} is not reachable ({exc}). Is it running?") from exc

    def _post(self, path: str, payload: dict) -> dict:
        try:
            r = self._http.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise ModelError(f"Ollama at {self.base_url} is not reachable ({exc}). Is it running?") from exc
        if r.status_code != 200:
            raise ModelError(f"Ollama error {r.status_code}: {r.text[:300]}")
        return r.json()

    def _stream(self, path: str, payload: dict) -> Iterator[dict]:
        try:
            with self._http.stream("POST", path, json=payload) as r:
                if r.status_code != 200:
                    r.read()
                    raise ModelError(f"Ollama error {r.status_code}: {r.text[:300]}")
                for line in r.iter_lines():
                    if line.strip():
                        yield json.loads(line)
        except httpx.HTTPError as exc:
            raise ModelError(f"Ollama at {self.base_url} is not reachable ({exc}). Is it running?") from exc


def detect_gpus() -> list[dict]:
    """NVIDIA GPUs and their memory (GB), via nvidia-smi. Empty if none or not NVIDIA."""
    import shutil
    import subprocess
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        name, _, mem = line.rpartition(",")
        try:
            gpus.append({"name": name.strip(), "memory_gb": round(float(mem) / 1024, 1)})
        except ValueError:
            continue
    return gpus


OLLAMA_WINDOWS_INSTALLER = "https://ollama.com/download/OllamaSetup.exe"
INSTALL_HELP = {
    "linux": "curl -fsSL https://ollama.com/install.sh | sh",
    "darwin": "Download the app from https://ollama.com/download/mac (or: brew install ollama)",
}


def install_ollama_windows(progress: Progress | None = None, client: httpx.Client | None = None) -> None:
    """Download the official Ollama installer and run it (per-user install, no admin rights).

    The installer shows its own small progress window and starts Ollama when it finishes.
    """
    import subprocess
    import tempfile
    target = Path(tempfile.gettempdir()) / "OllamaSetup.exe"
    http = client or httpx.Client(timeout=None)
    with http.stream("GET", OLLAMA_WINDOWS_INSTALLER, follow_redirects=True) as r:
        if r.status_code != 200:
            raise ModelError(f"Could not download the Ollama installer ({r.status_code}).")
        total, done = int(r.headers.get("content-length", 0)), 0
        with open(target, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress({"status": "downloading the Ollama installer", "completed": done, "total": total})
    if progress:
        progress({"status": "installing Ollama (follow its window)", "completed": 0, "total": 0})
    result = subprocess.run([str(target), "/SILENT", "/NORESTART"], check=False)
    if result.returncode != 0:
        raise ModelError(f"The Ollama installer stopped with code {result.returncode}.")


def find_ollama() -> str | None:
    """Path of the Ollama program if it is installed, else None."""
    import os
    import shutil
    found = shutil.which("ollama")
    if found:
        return found
    candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",  # Windows
                  Path("/Applications/Ollama.app/Contents/Resources/ollama"),                     # macOS
                  Path("/usr/local/bin/ollama")]
    return next((str(p) for p in candidates if str(p) and p.is_file()), None)


def start_ollama(executable: str) -> None:
    """Start 'ollama serve' in the background, detached from this process."""
    import subprocess
    import sys
    flags = 0
    if sys.platform.startswith("win"):
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
    subprocess.Popen([executable, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, creationflags=flags, start_new_session=not flags)


class OllamaModel:
    """A ChatModel bound to one Ollama model name."""

    def __init__(self, client: OllamaClient, name: str):
        self.client, self.name = client, name

    def chat(self, messages, *, temperature=None, seed=None, json_schema=None, max_tokens=None) -> ChatResult:
        return self.client.chat(self.name, messages, temperature=temperature, seed=seed, json_schema=json_schema,
                                max_tokens=max_tokens)


def download_from_huggingface(repo: str, filename: str, token: str | None, cache_dir: Path,
                              progress: Progress | None = None, client: httpx.Client | None = None) -> Path:
    """Download one GGUF file from Hugging Face (token needed for gated/private repos)."""
    url = f"https://huggingface.co/{repo}/resolve/main/{filename}"
    target = cache_dir / repo.replace("/", "__") / filename
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    partial = target.with_suffix(target.suffix + ".part")
    http = client or httpx.Client(timeout=None)
    with http.stream("GET", url, headers=headers, follow_redirects=True) as r:
        if r.status_code in (401, 403):
            raise ModelError(f"Hugging Face refused access to {repo} ({r.status_code}). "
                             "Check your token and that you accepted the model's licence.")
        if r.status_code != 200:
            raise ModelError(f"Hugging Face download failed ({r.status_code}) for {repo}/{filename}.")
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(partial, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress({"status": f"downloading {filename}", "completed": done, "total": total})
    partial.rename(target)
    return target


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ensure_model(client: OllamaClient, model, hf_token: str | None, cache_dir: Path,
                 progress: Progress | None = None) -> str:
    """Make sure a configured model is installed in Ollama; download it if not.

    ``model`` is an experiment ModelSettings. Returns what happened, for the log.
    """
    if model.source in ("fake", "demo"):
        return f"{model.source} model, nothing to download"
    if client.has_model(model.name):
        return "already installed"
    if model.source == "ollama":
        client.pull(model.name, progress)
        return "downloaded from the Ollama library"
    gguf = download_from_huggingface(model.hf_repo, model.hf_file, hf_token, cache_dir, progress)
    client.import_gguf(model.name, gguf, progress)
    return f"downloaded from Hugging Face ({model.hf_repo}) and registered"
