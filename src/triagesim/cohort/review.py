"""Manual case review: rebuild a saved cohort, explain single cases, save verdicts.

Everything here works on patient-level data. It is shown only in the local app
and saved only inside the run's folder in outputs/.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .build import CohortResult, build_cohort, matching_diagnoses
from .settings import CohortSettings

VERDICTS = ("Not reviewed", "Correct", "Incorrect", "Unsure")
REVIEW_FILE = "review.csv"


@dataclass
class SavedRun:
    run_dir: Path
    settings: CohortSettings
    result: CohortResult        # rebuilt from the saved settings
    reproduced: bool            # rebuilt cohort has exactly the saved stays


def rebuild(tables: dict[str, pd.DataFrame], run_dir: str | Path) -> SavedRun:
    """Rebuild a saved run from its settings and confirm it matches cohort.csv."""
    run_dir = Path(run_dir)
    settings = CohortSettings.from_yaml(run_dir / "settings.yaml")
    result = build_cohort(tables, settings)
    saved = pd.read_csv(run_dir / "cohort.csv", usecols=["stay_id"])
    reproduced = set(saved["stay_id"]) == set(result.cohort["stay_id"])
    return SavedRun(run_dir, settings, result, reproduced)


def sample_cases(ids: pd.Series, n: int, seed: int) -> list[int]:
    """A reproducible random sample of stay ids."""
    n = min(n, len(ids))
    return ids.sample(n=n, random_state=seed).tolist() if n else []


def case_details(tables: dict[str, pd.DataFrame], run: SavedRun, stay_id: int) -> dict:
    """Everything needed to judge one ED stay against the filters."""
    stays = tables["edstays"]
    stay = stays.loc[stays["stay_id"] == stay_id].iloc[0]
    patient = tables["patients"].loc[tables["patients"]["subject_id"] == stay["subject_id"]].iloc[0]
    triage = tables["triage"].loc[tables["triage"]["stay_id"] == stay_id]
    intime = pd.to_datetime(stay["intime"])

    in_cohort = stay_id in set(run.result.cohort["stay_id"])
    reason = run.result.excluded.loc[run.result.excluded["stay_id"] == stay_id, "excluded_at"]
    status = "Included" if in_cohort else f"Excluded at: {reason.iloc[0]}"

    diag = tables["ed_diagnosis"].loc[tables["ed_diagnosis"]["stay_id"] == stay_id]
    matched = set(matching_diagnoses(diag, run.settings).index) if (
        run.settings.icd10_codes or run.settings.icd9_codes) else set()
    diagnoses = diag.assign(matches_filter=diag.index.isin(matched)).sort_values("seq_num")[
        ["seq_num", "icd_code", "icd_version", "icd_title", "matches_filter"]]

    # All ED visits of this patient, to check the one-visit-per-patient rule.
    visits = stays.loc[stays["subject_id"] == stay["subject_id"], ["stay_id", "intime", "hadm_id"]].copy()
    visits["intime"] = pd.to_datetime(visits["intime"])
    excluded = run.result.excluded.set_index("stay_id")["excluded_at"]
    cohort_ids = set(run.result.cohort["stay_id"])
    visits["status"] = [("Included" if s in cohort_ids else f"Excluded at: {excluded.get(s, '?')}")
                        for s in visits["stay_id"]]
    visits["this case"] = visits["stay_id"] == stay_id
    visits = visits.sort_values("intime")

    facts = {
        "Status": status,
        "subject_id": int(stay["subject_id"]),
        "stay_id": int(stay_id),
        "hadm_id": "not admitted" if pd.isna(stay["hadm_id"]) else int(stay["hadm_id"]),
        "ED arrival": str(intime),
        "Sex": patient["gender"],
        "Age at visit": (f"{int(patient['anchor_age'] + intime.year - patient['anchor_year'])} "
                         f"(anchor_age {int(patient['anchor_age'])} in {int(patient['anchor_year'])}, "
                         f"visit in {intime.year})"),
        "Triage acuity (ESI)": ("missing" if triage.empty or pd.isna(triage["acuity"].iloc[0])
                                else int(triage["acuity"].iloc[0])),
        "Chief complaint": "" if triage.empty else str(triage["chiefcomplaint"].iloc[0]),
    }
    return {"facts": facts, "diagnoses": diagnoses.reset_index(drop=True),
            "visits": visits.reset_index(drop=True)}


def load_review(run_dir: str | Path) -> pd.DataFrame:
    path = Path(run_dir) / REVIEW_FILE
    if path.is_file():
        return pd.read_csv(path)
    return pd.DataFrame(columns=["stay_id", "group", "verdict", "note"])


def save_verdict(run_dir: str | Path, stay_id: int, group: str, verdict: str, note: str) -> None:
    """Add or update one case's verdict in the run's review.csv."""
    if verdict not in VERDICTS:
        raise ValueError(f"Unknown verdict: {verdict}")
    review = load_review(run_dir)
    review = review[review["stay_id"] != stay_id]
    row = pd.DataFrame([{"stay_id": stay_id, "group": group, "verdict": verdict, "note": note}])
    review = pd.concat([review, row], ignore_index=True) if len(review) else row
    review.to_csv(Path(run_dir) / REVIEW_FILE, index=False)
