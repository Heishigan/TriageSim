"""Apply the filters in a fixed order and record what each one removed."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from .. import __version__
from .icd import matches
from .settings import ESI_LEVELS, SEXES, CohortSettings

COHORT_COLUMNS = ["subject_id", "hadm_id", "stay_id", "intime", "gender", "anchor_age",
                  "anchor_year", "age_at_ed", "acuity", "chiefcomplaint", "disposition"]


@dataclass
class FlowStep:
    step: str
    ed_stays: int
    patients: int


@dataclass
class CohortResult:
    cohort: pd.DataFrame
    flow: list[FlowStep]
    excluded: pd.DataFrame      # stay_id, subject_id, excluded_at (the filter that removed it)

    def empty_steps(self) -> list[str]:
        """Filters after which no ED stays were left."""
        return [s.step for s in self.flow if s.ed_stays == 0]

    def summary(self) -> dict:
        """Aggregate numbers only; safe to show and share."""
        esi = self.cohort["acuity"].value_counts(dropna=False).sort_index()
        sex = self.cohort["gender"].value_counts().sort_index()
        return {
            "flow": [asdict(s) for s in self.flow],
            "esi_distribution": {("missing" if pd.isna(k) else str(int(k))): int(v) for k, v in esi.items()},
            "sex_distribution": {str(k): int(v) for k, v in sex.items()},
        }


def build_cohort(tables: dict[str, pd.DataFrame], settings: CohortSettings) -> CohortResult:
    """Return the ED stays that pass every filter in ``settings``."""
    settings.validate()
    flow: list[FlowStep] = []
    removed: list[pd.DataFrame] = []

    df = tables["edstays"].copy()
    df["intime"] = pd.to_datetime(df["intime"])
    df = df.merge(tables["patients"], on="subject_id", how="left")
    # MIMIC gives age in the patient's anchor year; shift it to the year of the visit.
    df["age_at_ed"] = df["anchor_age"] + (df["intime"].dt.year - df["anchor_year"])
    df = df.merge(tables["triage"], on="stay_id", how="left")
    flow.append(FlowStep("All ED stays", len(df), df["subject_id"].nunique()))

    def keep(mask: pd.Series, step: str) -> None:
        nonlocal df
        gone = df.loc[~mask, ["stay_id", "subject_id"]].assign(excluded_at=step)
        removed.append(gone)
        df = df[mask]
        flow.append(FlowStep(step, int(len(df)), int(df["subject_id"].nunique())))

    if settings.min_age is not None or settings.max_age is not None:
        low = settings.min_age if settings.min_age is not None else 0
        high = settings.max_age if settings.max_age is not None else 200
        keep(df["age_at_ed"].between(low, high),
             f"Age {low}-{high}" if settings.max_age is not None else f"Age {low} or older")

    if set(settings.sexes) != set(SEXES):
        keep(df["gender"].isin(settings.sexes), f"Sex: {', '.join(settings.sexes)}")

    if settings.admission == "admitted":
        keep(df["hadm_id"].notna(), "Admitted to hospital")
    elif settings.admission == "not_admitted":
        keep(df["hadm_id"].isna(), "Not admitted to hospital")

    if settings.icd10_codes or settings.icd9_codes:
        hits = matching_diagnoses(tables["ed_diagnosis"], settings)
        matched = (hits.groupby("stay_id")["icd_code"]
                   .agg(lambda c: ";".join(sorted(set(c.astype(str)))))
                   .rename("matched_icd_codes"))
        keep(df["stay_id"].isin(matched.index), "ICD code match in ED diagnoses")
        df = df.merge(matched, left_on="stay_id", right_index=True, how="left")

    if settings.require_acuity:
        keep(df["acuity"].notna(), "Triage acuity (ESI) recorded")

    if set(settings.esi_levels) != set(ESI_LEVELS):
        keep(df["acuity"].isin(settings.esi_levels),
             f"ESI level {', '.join(map(str, sorted(settings.esi_levels)))}")

    if settings.one_visit_per_patient:
        df = df.sort_values(["subject_id", "intime", "stay_id"])
        keep(~df["subject_id"].duplicated(keep="first"), "First qualifying visit per patient")

    columns = COHORT_COLUMNS + (["matched_icd_codes"] if "matched_icd_codes" in df else [])
    excluded = (pd.concat(removed, ignore_index=True) if removed
                else pd.DataFrame(columns=["stay_id", "subject_id", "excluded_at"]))
    return CohortResult(df[columns].reset_index(drop=True), flow, excluded)


def matching_diagnoses(diagnoses: pd.DataFrame, settings: CohortSettings) -> pd.DataFrame:
    """Rows of the ED diagnosis table whose code matches the settings."""
    hit = (((diagnoses["icd_version"] == 10) & matches(diagnoses["icd_code"], settings.icd10_codes))
           | ((diagnoses["icd_version"] == 9) & matches(diagnoses["icd_code"], settings.icd9_codes)))
    return diagnoses[hit]


def save_result(result: CohortResult, settings: CohortSettings,
                output_dir: str | Path, data_dir: str | Path | None = None) -> Path:
    """Write cohort.csv, settings.yaml and report.json to a new timestamped folder."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(output_dir) / f"{settings.name}_{stamp}"
    suffix = 2
    while run_dir.exists():                      # two builds in the same second
        run_dir = Path(output_dir) / f"{settings.name}_{stamp}-{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True)
    result.cohort.to_csv(run_dir / "cohort.csv", index=False)
    settings.to_yaml(run_dir / "settings.yaml")
    report = {"tool": "triagesim", "version": __version__,
              "created": datetime.now().isoformat(timespec="seconds"),
              "data_dir": str(data_dir) if data_dir else None, **result.summary()}
    (run_dir / "report.json").write_text(json.dumps(report, indent=2))
    return run_dir
