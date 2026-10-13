"""The MIMIC files TriageSim needs, where they must be placed, and how to check them.

Each file has one fixed place inside the data folder. Files are grouped by what
needs them: the cohort builder, the case builder, and optional labels.

Checking reads only the header line of each file, never patient rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


MIMIC_IV = ("MIMIC-IV v3.1", "https://physionet.org/content/mimiciv/3.1/")
MIMIC_ED = ("MIMIC-IV-ED v2.2", "https://physionet.org/content/mimic-iv-ed/2.2/")
MIMIC_NOTE = ("MIMIC-IV-Note v2.2", "https://physionet.org/content/mimic-iv-note/2.2/")

PURPOSES = {"cohort": "Cohort builder", "cases": "Case builder", "labels": "Labels (optional)"}


@dataclass(frozen=True)
class TableSpec:
    key: str
    relative_path: str          # fixed place inside the data folder
    columns: tuple[str, ...]    # columns this tool needs
    source: str                 # PhysioNet project that provides it
    url: str                    # where to download it
    purpose: str = "cohort"     # cohort | cases | labels


TABLES = (
    TableSpec("patients", "hosp/patients.csv.gz",
              ("subject_id", "gender", "anchor_age", "anchor_year"), "MIMIC-IV v3.1",
              "https://physionet.org/content/mimiciv/3.1/"),
    TableSpec("edstays", "ed/edstays.csv.gz",
              ("subject_id", "hadm_id", "stay_id", "intime", "disposition"), "MIMIC-IV-ED v2.2",
              "https://physionet.org/content/mimic-iv-ed/2.2/"),
    TableSpec("triage", "ed/triage.csv.gz",
              ("stay_id", "acuity", "chiefcomplaint"), "MIMIC-IV-ED v2.2",
              "https://physionet.org/content/mimic-iv-ed/2.2/"),
    TableSpec("ed_diagnosis", "ed/diagnosis.csv.gz",
              ("stay_id", "seq_num", "icd_code", "icd_version", "icd_title"), "MIMIC-IV-ED v2.2",
              "https://physionet.org/content/mimic-iv-ed/2.2/"),
    TableSpec("triage_vitals", "ed/triage.csv.gz",
              ("stay_id", "temperature", "heartrate", "resprate", "o2sat", "sbp", "dbp", "pain"),
              *MIMIC_ED, purpose="cases"),
    TableSpec("edstays_arrival", "ed/edstays.csv.gz", ("stay_id", "arrival_transport"),
              *MIMIC_ED, purpose="cases"),
    TableSpec("medrecon", "ed/medrecon.csv.gz", ("stay_id", "name"), *MIMIC_ED, purpose="cases"),
    TableSpec("discharge", "note/discharge.csv.gz", ("hadm_id", "note_seq", "text"),
              *MIMIC_NOTE, purpose="cases"),
    TableSpec("hosp_diagnoses", "hosp/diagnoses_icd.csv.gz",
              ("hadm_id", "icd_code", "icd_version"), *MIMIC_IV, purpose="labels"),
)

MODULE_FOLDERS = sorted({t.relative_path.split("/")[0] for t in TABLES})


def tables_for(*purposes: str) -> tuple[TableSpec, ...]:
    return tuple(t for t in TABLES if t.purpose in purposes)


def layout_tree(root_name: str = "data", purposes: tuple[str, ...] = tuple(PURPOSES)) -> str:
    """The expected folder layout as a text tree (each file listed once)."""
    wanted = tables_for(*purposes)
    modules = sorted({t.relative_path.split("/")[0] for t in wanted})
    lines = [f"{root_name}/"]
    for i, module in enumerate(modules):
        last_module = i == len(modules) - 1
        lines.append(f"{'└──' if last_module else '├──'} {module}/")
        files = list(dict.fromkeys(t.relative_path.split("/")[1] for t in wanted
                                   if t.relative_path.startswith(module + "/")))
        for j, name in enumerate(files):
            branch = "└──" if j == len(files) - 1 else "├──"
            lines.append(f"{'    ' if last_module else '│   '}{branch} {name}")
    return "\n".join(lines)


@dataclass
class CheckResult:
    table: TableSpec
    path: Path | None
    ok: bool
    message: str


class DataLoadError(Exception):
    """A data file passed the check but could not be read in full."""


def ensure_layout(data_dir: str | Path) -> None:
    """Create the empty data folder and its module subfolders if they are missing."""
    for module in MODULE_FOLDERS:
        (Path(data_dir) / module).mkdir(parents=True, exist_ok=True)


def check_data(data_dir: str | Path, purposes: tuple[str, ...] = ("cohort",)) -> list[CheckResult]:
    """Check that every file needed for ``purposes`` is in place with the needed columns."""
    data_dir = Path(data_dir)
    results = []
    for spec in tables_for(*purposes):
        path = data_dir / spec.relative_path
        if not path.is_file():
            elsewhere = sorted(data_dir.glob(f"**/{path.name}")) if data_dir.is_dir() else []
            if elsewhere:
                found = elsewhere[0].relative_to(data_dir).as_posix()
                message = f"Found at data/{found}. Move it to data/{spec.relative_path}."
            else:
                message = f"Missing. Download it from {spec.source} and place it at data/{spec.relative_path}."
            results.append(CheckResult(spec, None, False, message))
            continue
        try:
            header = pd.read_csv(path, nrows=0).columns
        except Exception as exc:  # unreadable, empty or corrupt file
            results.append(CheckResult(spec, path, False, f"Cannot read the file ({exc}). Download it again."))
            continue
        missing = [c for c in spec.columns if c not in header]
        if missing:
            results.append(CheckResult(spec, path, False, f"Missing columns: {', '.join(missing)}. "
                                       f"Is this the file from {spec.source}?"))
        else:
            results.append(CheckResult(spec, path, True, "OK"))
    return results


def load_tables(data_dir: str | Path, purposes: tuple[str, ...] = ("cohort",),
                skip: tuple[str, ...] = ()) -> dict[str, pd.DataFrame]:
    """Load the needed columns of every table for ``purposes``. Raises if the check fails.

    Tables listed in ``skip`` are checked but not loaded (e.g. the large note file,
    which the case builder reads in chunks).
    """
    results = check_data(data_dir, purposes)
    failed = [r for r in results if not r.ok]
    if failed:
        lines = [f"{r.table.relative_path}: {r.message}" for r in failed]
        raise FileNotFoundError("Data check failed:\n" + "\n".join(lines))
    tables = {}
    for r in results:
        if r.table.key in skip:
            continue
        try:
            tables[r.table.key] = pd.read_csv(r.path, usecols=list(r.table.columns))
        except Exception as exc:  # e.g. a download that stopped halfway
            raise DataLoadError(
                f"{r.table.relative_path} could not be read completely ({type(exc).__name__}: {exc}). "
                "The file may be incomplete or damaged; download it again.") from exc
    return tables
