"""Remember small user choices (the data folder) between launches.

Stored in ~/.triagesim/preferences.json, outside the repository.
Set TRIAGESIM_HOME to use another folder (the tests do this).
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def prefs_file() -> Path:
    home = os.environ.get("TRIAGESIM_HOME") or Path.home() / ".triagesim"
    return Path(home) / "preferences.json"


def load(path: Path | None = None) -> dict:
    path = path or prefs_file()
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(prefs: dict, path: Path | None = None) -> None:
    path = path or prefs_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prefs, indent=2))


def pick_folder() -> str | None:
    """Open the system folder dialog. Returns None if cancelled or unavailable."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)   # show the dialog in front of the browser
    folder = filedialog.askdirectory(title="Choose the folder with your MIMIC files")
    root.destroy()
    return folder or None
