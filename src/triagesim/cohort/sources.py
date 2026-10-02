"""Where the MIMIC files are expected and how to check them.

The user copies the PhysioNet downloads into one data folder. Files are found
by their module folder and name (e.g. ``hosp/patients.csv.gz``) anywhere below
that folder, so both ``data/hosp/...`` and ``data/mimic-iv-3.1/hosp/...`` work.

Checking reads only the header line of each file, never patient rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class TableSpec:
    key: str
    relative_path: str          # module folder + file name
    columns: tuple[str, ...]    # columns this tool needs
    source: str                 # PhysioNet project that provides it
    url: str                    # where to download it


TABLES = (
    TableSpec("patients", "hosp/patients.csv.gz",
              ("subject_id", "gender", "anchor_age", "anchor_year"), "MIMIC-IV v3.1",
              "https://physionet.org/content/mimiciv/3.1/"),
    TableSpec("edstays", "ed/edstays.csv.gz",
              ("subject_id", "hadm_id", "stay_id", "intime"), "MIMIC-IV-ED v2.2",
              "https://physionet.org/content/mimic-iv-ed/2.2/"),
    TableSpec("triage", "ed/triage.csv.gz",
              ("stay_id", "acuity", "chiefcomplaint"), "MIMIC-IV-ED v2.2",
              "https://physionet.org/content/mimic-iv-ed/2.2/"),
    TableSpec("ed_diagnosis", "ed/diagnosis.csv.gz",
              ("stay_id", "seq_num", "icd_code", "icd_version", "icd_title"), "MIMIC-IV-ED v2.2",
              "https://physionet.org/content/mimic-iv-ed/2.2/"),
)


@dataclass
class CheckResult:
    table: TableSpec
    path: Path | None
    ok: bool
    message: str
    note: str = ""              # non-blocking warning, e.g. duplicate copies


class DataLoadError(Exception):
    """A data file passed the check but could not be read in full."""


def find_table(data_dir: Path, spec: TableSpec) -> list[Path]:
    """All copies of ``spec`` below ``data_dir`` (.csv.gz preferred over .csv)."""
    module, filename = spec.relative_path.split("/")
    for name in (filename, filename.removesuffix(".gz")):
        found = sorted(p for p in data_dir.glob(f"**/{module}/{name}") if p.is_file())
        if found:
            return found
    return []


def check_data(data_dir: str | Path) -> list[CheckResult]:
    """Check that every required table exists and has the needed columns."""
    data_dir = Path(data_dir)
    results = []
    for spec in TABLES:
        copies = find_table(data_dir, spec) if data_dir.is_dir() else []
        if not copies:
            results.append(CheckResult(spec, None, False,
                                       f"Not found. Expected {spec.relative_path} from {spec.source}."))
            continue
        path = copies[0]
        note = ""
        if len(copies) > 1:
            note = (f"{len(copies)} copies found; using {path.relative_to(data_dir)}. "
                    "Remove the others to avoid mixing versions.")
        try:
            header = pd.read_csv(path, nrows=0).columns
        except Exception as exc:  # unreadable, empty or corrupt file
            results.append(CheckResult(spec, path, False, f"Cannot read file ({exc}). Download it again.", note))
            continue
        missing = [c for c in spec.columns if c not in header]
        if missing:
            results.append(CheckResult(spec, path, False, f"Missing columns: {', '.join(missing)}. "
                                       f"Is this the file from {spec.source}?", note))
        else:
            results.append(CheckResult(spec, path, True, "OK", note))
    return results


def load_tables(data_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Load the needed columns of every table. Raises if the check fails."""
    results = check_data(data_dir)
    failed = [r for r in results if not r.ok]
    if failed:
        lines = [f"{r.table.relative_path}: {r.message}" for r in failed]
        raise FileNotFoundError("Data check failed:\n" + "\n".join(lines))
    tables = {}
    for r in results:
        try:
            tables[r.table.key] = pd.read_csv(r.path, usecols=list(r.table.columns))
        except Exception as exc:  # e.g. a download that stopped halfway
            raise DataLoadError(
                f"{r.table.relative_path} could not be read completely ({type(exc).__name__}: {exc}). "
                "The file may be incomplete or damaged; download it again.") from exc
    return tables
