"""Build case files from a saved cohort.

Each case has four parts, kept strictly apart:
  nurse_view    what the triage nurse can see or measure at arrival
  patient_view  what the patient knows (redacted HPI, history, home medications)
  reference     answers used only for evaluation (nurse ESI, disposition, labels)
  audit         what redaction did, for review
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd
import yaml

from ..cohort.icd import matches
from .notes import redact_hpi, split_sections

PATIENT_SECTIONS = ("past_medical_history", "social_history", "allergies")
VITALS = {"temperature": "Temperature (F)", "heartrate": "Heart rate", "resprate": "Respiratory rate",
          "o2sat": "O2 saturation (%)", "sbp": "Systolic BP", "dbp": "Diastolic BP", "pain": "Pain (0-10)"}


@dataclass
class CaseSettings:
    require_hpi: bool = True
    redact_hpi: bool = True
    patient_sections: list[str] = field(default_factory=lambda: list(PATIENT_SECTIONS))
    include_medications: bool = True
    head_injury_icd10: list[str] = field(default_factory=lambda: ["S06"])
    head_injury_icd9: list[str] = field(default_factory=lambda: ["850-854"])

    def to_yaml(self, path: Path) -> None:
        path.write_text(yaml.safe_dump(asdict(self), sort_keys=False))


def read_discharge_notes(path: Path, hadm_ids: set, progress: Callable[[int], None] | None = None,
                         chunksize: int = 20_000) -> dict:
    """hadm_id -> text of its first discharge note, reading the large file in chunks."""
    notes: dict = {}
    seq: dict = {}
    rows = 0
    for chunk in pd.read_csv(path, usecols=["hadm_id", "note_seq", "text"], chunksize=chunksize):
        rows += len(chunk)
        hit = chunk[chunk["hadm_id"].isin(hadm_ids)]
        for hadm, note_seq, text in hit.itertuples(index=False):
            if hadm not in seq or note_seq < seq[hadm]:
                seq[hadm], notes[hadm] = note_seq, text
        if progress:
            progress(rows)
    return notes


def _clean(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value.item() if hasattr(value, "item") else value


def build_cases(cohort: pd.DataFrame, tables: dict[str, pd.DataFrame], notes: dict,
                settings: CaseSettings) -> tuple[list[dict], list[dict]]:
    """Return (cases, flow). ``notes`` maps hadm_id -> discharge note text."""
    flow = [{"step": "Cohort cases", "cases": int(len(cohort))}]
    vitals = tables["triage_vitals"].set_index("stay_id")
    arrival = tables["edstays_arrival"].set_index("stay_id")["arrival_transport"]
    meds = (tables["medrecon"].dropna(subset=["name"]).groupby("stay_id")["name"]
            .agg(lambda n: sorted(set(map(str, n)))) if settings.include_medications else pd.Series(dtype=object))
    head_injury = None
    if "hosp_diagnoses" in tables:
        diag = tables["hosp_diagnoses"]
        hit = (((diag["icd_version"] == 10) & matches(diag["icd_code"], settings.head_injury_icd10))
               | ((diag["icd_version"] == 9) & matches(diag["icd_code"], settings.head_injury_icd9)))
        head_injury = set(diag.loc[hit, "hadm_id"])

    cases, with_note, with_hpi = [], 0, 0
    for row in cohort.sort_values("stay_id").itertuples(index=False):
        text = notes.get(row.hadm_id)
        sections = split_sections(text) if text else {}
        with_note += text is not None
        hpi = sections.get("hpi")
        with_hpi += hpi is not None
        if settings.require_hpi and not hpi:
            continue
        red = redact_hpi(hpi or "") if settings.redact_hpi else None
        v = vitals.loc[row.stay_id] if row.stay_id in vitals.index else None
        cases.append({
            "case_id": f"case-{len(cases) + 1:05d}",
            "stay_id": int(row.stay_id), "subject_id": int(row.subject_id),
            "hadm_id": None if pd.isna(row.hadm_id) else int(row.hadm_id),
            "nurse_view": {
                "age": int(row.age_at_ed), "sex": row.gender,
                "chief_complaint": _clean(row.chiefcomplaint),
                "arrival_transport": _clean(arrival.get(row.stay_id)),
                "vitals": {k: (None if v is None else _clean(v[k])) for k in VITALS},
            },
            "patient_view": {
                "age": int(row.age_at_ed), "sex": row.gender,
                "chief_complaint": _clean(row.chiefcomplaint),
                "hpi": red.text if red else (hpi or ""),
                **{s: sections.get(s, "") for s in settings.patient_sections},
                "medications": list(meds.get(row.stay_id, [])) if settings.include_medications else [],
            },
            "reference": {
                "esi": None if pd.isna(row.acuity) else int(row.acuity),
                "disposition": _clean(getattr(row, "disposition", None)),
                "admitted": not pd.isna(row.hadm_id),
                "head_injury_icd": None if head_injury is None else bool(row.hadm_id in head_injury),
            },
            "audit": {
                "hpi_found": hpi is not None,
                "hpi_original_chars": len(hpi or ""),
                "hpi_redacted": bool(red and red.changed),
                "ed_course_cut": bool(red and red.ed_course_cut),
                "removed_sentences": dict(red.removed) if red else {},
            },
        })
    flow.append({"step": "Discharge note found", "cases": with_note})
    if settings.require_hpi:
        flow.append({"step": "HPI section found", "cases": len(cases)})
    return cases, flow


def summarize(cases: list[dict], flow: list[dict]) -> dict:
    """Aggregate numbers only."""
    n = len(cases)
    removed: dict[str, int] = {}
    for c in cases:
        for k, v in c["audit"]["removed_sentences"].items():
            removed[k] = removed.get(k, 0) + v
    labels = [c["reference"]["head_injury_icd"] for c in cases]
    return {
        "flow": flow,
        "cases": n,
        "hpi_redacted": sum(c["audit"]["hpi_redacted"] for c in cases),
        "ed_course_cut": sum(c["audit"]["ed_course_cut"] for c in cases),
        "removed_sentences_by_rule": removed,
        "with_medications": sum(bool(c["patient_view"]["medications"]) for c in cases),
        "with_vitals": sum(c["nurse_view"]["vitals"]["heartrate"] is not None for c in cases),
        "head_injury_icd_positive": None if any(x is None for x in labels) else sum(labels),
    }


def save_cases(run_dir: Path, cases: list[dict], flow: list[dict], settings: CaseSettings) -> dict:
    """Write cases.jsonl, cases_settings.yaml and cases_report.json into the cohort folder."""
    with open(run_dir / "cases.jsonl", "w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
    settings.to_yaml(run_dir / "cases_settings.yaml")
    report = summarize(cases, flow)
    (run_dir / "cases_report.json").write_text(json.dumps(report, indent=2))
    return report


def load_cases(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / "cases.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
