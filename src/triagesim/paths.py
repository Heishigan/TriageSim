"""Fixed folders inside the TriageSim repository.

    TriageSim/
      data/       MIMIC files, placed by the user in a fixed layout (never committed)
      outputs/    built cohorts (never committed)
      configs/    filter presets

Tests and scripts can point elsewhere with TRIAGESIM_DATA_DIR / TRIAGESIM_OUTPUT_DIR.
"""
from __future__ import annotations

import os
from pathlib import Path

# src/triagesim/paths.py -> repository root is two levels above the package.
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "configs"
COHORT_PRESETS = CONFIG_DIR / "cohorts"
EXPERIMENT_PRESETS = CONFIG_DIR / "experiments"


def data_dir() -> Path:
    return Path(os.environ.get("TRIAGESIM_DATA_DIR") or REPO_ROOT / "data")


def output_dir() -> Path:
    return Path(os.environ.get("TRIAGESIM_OUTPUT_DIR") or REPO_ROOT / "outputs")


def cohorts_dir() -> Path:
    """Saved cohorts (and their case files)."""
    return output_dir() / "cohorts"


def runs_dir() -> Path:
    """Experiment runs."""
    return output_dir() / "runs"
