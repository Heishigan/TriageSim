from triagesim.cohort.build import build_cohort, save_result
from triagesim.cohort.review import case_details, load_review, rebuild, sample_cases, save_verdict
from triagesim.cohort.settings import CohortSettings


def saved_run(tables, tmp_path):
    s = CohortSettings.from_yaml("configs/cohorts/elderly_falls.yaml")
    return save_result(build_cohort(tables, s), s, tmp_path)


def test_every_excluded_stay_has_one_reason(tables):
    result = build_cohort(tables, CohortSettings.from_yaml("configs/cohorts/elderly_falls.yaml"))
    ex = result.excluded.set_index("stay_id")["excluded_at"].to_dict()
    assert ex == {21: "Age 65 or older", 31: "Admitted to hospital",
                  41: "ICD code match in ED diagnoses", 51: "Triage acuity (ESI) recorded",
                  12: "First qualifying visit per patient"}
    assert len(ex) + len(result.cohort) == len(tables["edstays"])


def test_rebuild_reproduces_saved_cohort(tables, tmp_path):
    run = rebuild(tables, saved_run(tables, tmp_path))
    assert run.reproduced


def test_rebuild_detects_changed_data(tables, tmp_path):
    run_dir = saved_run(tables, tmp_path)
    tables["triage"].loc[tables["triage"]["stay_id"] == 61, "acuity"] = None
    assert not rebuild(tables, run_dir).reproduced


def test_case_details_explain_inclusion_and_exclusion(tables, tmp_path):
    run = rebuild(tables, saved_run(tables, tmp_path))
    included = case_details(tables, run, 11)
    assert included["facts"]["Status"] == "Included"
    assert included["diagnoses"]["matches_filter"].tolist() == [True, False]   # W19 yes, S09 no
    assert included["visits"]["status"].tolist() == [
        "Included", "Excluded at: First qualifying visit per patient"]
    assert included["facts"]["Age at visit"].startswith("70")
    assert case_details(tables, run, 41)["facts"]["Status"] == "Excluded at: ICD code match in ED diagnoses"
    not_admitted = case_details(tables, run, 31)
    assert not_admitted["facts"]["ED disposition"] == "TRANSFER"
    assert not_admitted["visits"]["disposition"].tolist() == ["TRANSFER"]


def test_sample_is_reproducible(tables):
    ids = tables["edstays"]["stay_id"]
    assert sample_cases(ids, 3, seed=5) == sample_cases(ids, 3, seed=5)
    assert len(sample_cases(ids, 100, seed=1)) == len(ids)


def test_verdicts_are_saved_and_updated(tmp_path):
    save_verdict(tmp_path, 11, "Included cases", "Correct", "")
    save_verdict(tmp_path, 11, "Included cases", "Incorrect", "wrong code")
    review = load_review(tmp_path)
    assert review[["stay_id", "verdict", "note"]].values.tolist() == [[11, "Incorrect", "wrong code"]]
