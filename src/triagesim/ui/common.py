"""Pieces shared by the pages: remembered folders, cached data, past runs."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from triagesim import preferences
from triagesim.cohort.sources import load_tables

# configs/ at the repository root (src/triagesim/ui/common.py -> 3 levels up).
PRESET_DIR = Path(__file__).resolve().parents[3] / "configs"


def remembered(key: str, default: str) -> str:
    """A folder choice kept in the session, starting from the saved preference."""
    if key not in st.session_state:
        st.session_state[key] = preferences.load().get(key, default)
    return st.session_state[key]


def remember(key: str, value: str) -> None:
    st.session_state[key] = value
    prefs = preferences.load()
    if prefs.get(key) != value:
        preferences.save({**prefs, key: value})


def files_signature(checks) -> tuple:
    """Paths, sizes and modification times: changes when a file is replaced."""
    return tuple((str(r.path), r.path.stat().st_size, r.path.stat().st_mtime) for r in checks)


@st.cache_data(show_spinner="Loading MIMIC tables (the first time takes a minute)...", max_entries=1)
def cached_tables(data_dir: str, signature: tuple) -> dict[str, pd.DataFrame]:
    return load_tables(data_dir)


def list_runs(output_dir: str) -> list[Path]:
    """Saved cohort builds, newest first."""
    root = Path(output_dir)
    if not root.is_dir():
        return []
    runs = [p for p in root.iterdir() if (p / "cohort.csv").is_file() and (p / "settings.yaml").is_file()]
    return sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)
