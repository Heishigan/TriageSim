"""User settings kept outside the repository (Ollama address, Hugging Face token).

Stored in ~/.triagesim/settings.json (or $TRIAGESIM_HOME). The HF token is never
written into the repository or into run folders.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {"ollama_url": "http://localhost:11434", "hf_token": ""}


def _file() -> Path:
    home = os.environ.get("TRIAGESIM_HOME") or Path.home() / ".triagesim"
    return Path(home) / "settings.json"


def load() -> dict:
    try:
        data = json.loads(_file().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    settings = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    if os.environ.get("HF_TOKEN") and not settings["hf_token"]:
        settings["hf_token"] = os.environ["HF_TOKEN"]
    return settings


def save(changes: dict) -> dict:
    current = load()
    current.update({k: v for k, v in changes.items() if k in DEFAULTS and v is not None})
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2))
    try:
        path.chmod(0o600)          # the token is private
    except OSError:
        pass
    return current


def public(settings: dict) -> dict:
    """Settings safe to send to the browser (token masked)."""
    token = settings.get("hf_token") or ""
    return {"ollama_url": settings["ollama_url"], "hf_token_set": bool(token),
            "hf_token_hint": f"hf_...{token[-4:]}" if len(token) > 8 else ""}
