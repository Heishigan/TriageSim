"""The local API, end to end with invented data and the demo model."""
import gzip
import json
import time

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from conftest import NOTE_11, NOTE_61


@pytest.fixture
def api(app_dirs, case_tables, tmp_path, monkeypatch):
    data_dir, _ = app_dirs
    monkeypatch.setenv("TRIAGESIM_HOME", str(tmp_path / "home"))
    for key, rel in {"medrecon": "ed/medrecon.csv.gz", "hosp_diagnoses": "hosp/diagnoses_icd.csv.gz"}.items():
        case_tables[key].to_csv(data_dir / rel, index=False)
    # edstays/triage need the extra case-builder columns too
    stays = pd.read_csv(data_dir / "ed/edstays.csv.gz").merge(case_tables["edstays_arrival"], on="stay_id")
    stays.to_csv(data_dir / "ed/edstays.csv.gz", index=False)
    triage = pd.read_csv(data_dir / "ed/triage.csv.gz").merge(case_tables["triage_vitals"], on="stay_id")
    triage.to_csv(data_dir / "ed/triage.csv.gz", index=False)
    (data_dir / "note").mkdir(exist_ok=True)
    pd.DataFrame({"hadm_id": [101, 601], "note_seq": [1, 1], "text": [NOTE_11, NOTE_61]}).to_csv(
        data_dir / "note/discharge.csv.gz", index=False)
    from triagesim.server import app as server
    server._tables_cache.clear()
    return TestClient(server.app)


def wait_job(api, job_id, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        job = api.get(f"/api/jobs/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def cohort_with_cases(api):
    preset = next(p for p in api.get("/api/cohort-presets").json() if p["name"] == "elderly_falls")
    built = api.post("/api/cohorts", json=preset["settings"]).json()
    assert [s["ed_stays"] for s in built["flow"]] == [7, 6, 5, 4, 3, 2]
    job = wait_job(api, api.post(f"/api/cohorts/{built['name']}/cases").json()["id"])
    assert job["state"] == "done", job
    return built["name"]


def demo(config):
    for agent in ("nurse", "patient", "evaluator"):
        if config.get(agent):
            config[agent]["model"]["source"] = "demo"
    return config


def test_data_check_groups(api):
    data = api.get("/api/data").json()
    assert [g["purpose"] for g in data["groups"]] == ["cohort", "cases", "labels"]
    assert all(g["ready"] for g in data["groups"])


def test_cohort_cases_run_results(api):
    name = cohort_with_cases(api)
    detail = api.get(f"/api/cohorts/{name}").json()
    assert detail["cases_report"]["cases"] == 1          # stay 61 has no HPI
    assert api.get(f"/api/cohorts/{name}/cases").json()["total"] == 1

    preset = next(p for p in api.get("/api/experiment-presets").json() if p["name"] == "interview")
    config = demo(preset["config"]) | {"cohort": name}
    assert api.post("/api/experiments/validate", json=config).json() == {"valid": True, "errors": []}
    run = api.post("/api/runs", json=config).json()["name"]
    wait_job(api, run)
    assert api.get(f"/api/runs/{run}").json()["status"]["state"] == "completed"

    events = api.get(f"/api/runs/{run}/events").text
    assert '"type": "case_done"' in events and "event: end" in events

    results = api.get(f"/api/runs/{run}/results").json()
    assert results["metrics"]["cases"] == 1 and len(results["cases"]) == 1
    case_id = results["cases"][0]["case_id"]
    assert api.get(f"/api/runs/{run}/cases/{case_id}").json()["transcript"][0]["speaker"] == "nurse"
    assert "Demo summary" in api.post(f"/api/runs/{run}/summary").json()["summary"]
    assert api.get(f"/api/compare?a={run}&b={run}").json()["p_value"] == 1.0
    assert api.get("/api/runs").json()[0]["state"] == "completed"


def test_invalid_experiment_is_explained(api):
    preset = next(p for p in api.get("/api/experiment-presets").json() if p["name"] == "interview")
    config = preset["config"]
    config["nurse"]["sees"].append("esi")
    out = api.post("/api/experiments/validate", json=config).json()
    assert not out["valid"] and any("reference answers" in e for e in out["errors"])
    assert api.post("/api/runs", json=config).status_code == 422


def test_run_needs_cases(api):
    preset = next(p for p in api.get("/api/experiment-presets").json() if p["name"] == "interview")
    r = api.post("/api/runs", json=demo(preset["config"]))
    assert r.status_code == 400 and "Build the cohort" in r.json()["detail"]


def test_review_through_api(api):
    name = cohort_with_cases(api)
    review = api.get(f"/api/cohorts/{name}/review?group=included&n=5").json()
    assert review["reproduced"] and review["pool"] == 2
    stay = review["cases"][0]["stay_id"]
    assert api.post(f"/api/cohorts/{name}/review",
                    json={"stay_id": stay, "group": "included", "verdict": "Correct"}).json() == {"saved": True}


def test_settings_mask_the_token(api):
    out = api.put("/api/settings", json={"hf_token": "hf_abcdefghijklmnop"}).json()
    assert out == {"ollama_url": "http://localhost:11434", "hf_token_set": True, "hf_token_hint": "hf_...mnop"}
    assert "abcdefgh" not in json.dumps(api.get("/api/health").json())


def test_unknown_names_are_404(api):
    assert api.get("/api/runs/nope").status_code == 404
    assert api.get("/api/cohorts/..%2F..").status_code == 404


def test_presets_come_with_defaults_filled_in(api):
    preset = next(p for p in api.get("/api/experiment-presets").json() if p["name"] == "interview")
    assert "review the conversation" in preset["config"]["nurse"]["self_review"]["prompt"]
    assert preset["config"]["patient"]["retrieval_top_k"] == 3
