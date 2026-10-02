"""Pieces shared by the pages: cached data and past runs."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from triagesim.cohort.sources import load_tables


def files_signature(checks) -> tuple:
    """Paths, sizes and modification times: changes when a file is replaced."""
    return tuple((str(r.path), r.path.stat().st_size, r.path.stat().st_mtime) for r in checks)


@st.cache_data(show_spinner="Loading MIMIC tables (the first time takes a minute)...", max_entries=1)
def cached_tables(data_dir: str, signature: tuple) -> dict[str, pd.DataFrame]:
    # ``signature`` makes the cache reload when a file is replaced, e.g. after a re-download.
    return load_tables(data_dir)


def list_runs(output_dir: Path) -> list[Path]:
    """Saved cohort builds, newest first."""
    if not output_dir.is_dir():
        return []
    runs = [p for p in output_dir.iterdir() if (p / "cohort.csv").is_file() and (p / "settings.yaml").is_file()]
    return sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)


def open_folder(path: Path) -> None:
    """Open a folder in the system file manager (Explorer, Finder, ...)."""
    import os
    import subprocess
    import sys
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - local folder chosen by the app, not the user
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
