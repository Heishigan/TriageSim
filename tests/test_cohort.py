import json

from triagesim.cohort.build import build_cohort, save_result
from triagesim.cohort.settings import CohortSettings


def test_no_filters_keeps_everything(tables):
    result = build_cohort(tables, CohortSettings())
    assert len(result.cohort) == 7
    assert [s.step for s in result.flow] == ["All ED stays"]


def test_elderly_falls_preset(tables):
    result = build_cohort(tables, CohortSettings.from_yaml("configs/elderly_falls.yaml"))
    assert sorted(result.cohort["stay_id"]) == [11, 61]
    assert [s.ed_stays for s in result.flow] == [7, 6, 5, 4, 3, 2]
    # Age is shifted to the visit year: subject 6 is 88 in 2150, 90 in 2152.
    assert result.cohort.set_index("stay_id").loc[61, "age_at_ed"] == 90


def test_matched_codes_are_reported(tables):
    s = CohortSettings(icd10_codes=["W00-W19", "S09"])
    cohort = build_cohort(tables, s).cohort.set_index("stay_id")
    assert cohort.loc[11, "matched_icd_codes"] == "S0990XA;W19XXXA"


def test_sex_age_and_esi_filters(tables):
    s = CohortSettings(min_age=60, max_age=85, sexes=["F"], esi_levels=[2])
    assert sorted(build_cohort(tables, s).cohort["stay_id"]) == [11, 31]


def test_not_admitted(tables):
    s = CohortSettings(admission="not_admitted")
    assert build_cohort(tables, s).cohort["stay_id"].tolist() == [31]


def test_save_result(tables, tmp_path):
    s = CohortSettings(name="demo", min_age=65)
    run_dir = save_result(build_cohort(tables, s), s, tmp_path)
    assert {p.name for p in run_dir.iterdir()} == {"cohort.csv", "settings.yaml", "report.json"}
    report = json.loads((run_dir / "report.json").read_text())
    assert report["flow"][-1]["ed_stays"] == 6
