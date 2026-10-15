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
    assert out == {"ollama_url": "http://127.0.0.1:11434", "hf_token_set": True, "hf_token_hint": "hf_...mnop"}
    assert "abcdefgh" not in json.dumps(api.get("/api/health").json())


def test_unknown_names_are_404(api):
    assert api.get("/api/runs/nope").status_code == 404
    assert api.get("/api/cohorts/..%2F..").status_code == 404


def test_presets_come_with_defaults_filled_in(api):
    preset = next(p for p in api.get("/api/experiment-presets").json() if p["name"] == "interview")
    assert preset["config"]["nurse"]["max_turns"] == 12 and "self_review" not in preset["config"]["nurse"]
    assert preset["config"]["patient"]["retrieval_top_k"] == 3


def test_ping_does_not_wait_for_a_slow_ollama(api, monkeypatch):
    """On Windows a stopped Ollama can take seconds to refuse; the launcher must not wait for it."""
    from triagesim.llm.ollama import OllamaClient
    monkeypatch.setattr(OllamaClient, "version", lambda self: time.sleep(5))
    start = time.time()
    assert api.get("/api/ping").json() == {"ok": True}
    assert time.time() - start < 1


def test_status_checks_use_a_short_timeout():
    from triagesim.server.app import _ollama
    assert _ollama(quick=True)._http.timeout.connect == 3.0
    assert _ollama()._http.timeout.connect == 600.0


def test_health_reports_whether_ollama_is_installed(api, monkeypatch):
    import triagesim.server.app as server
    monkeypatch.setattr(server, "find_ollama", lambda: None)
    ollama = api.get("/api/health").json()["ollama"]
    assert ollama["reachable"] is False and ollama["installed"] is False and ollama["installing"] is False
    assert api.post("/api/ollama/start").status_code == 404


def test_start_ollama_when_installed(api, monkeypatch):
    import triagesim.server.app as server
    from triagesim.llm.ollama import OllamaClient
    started = []
    monkeypatch.setattr(server, "find_ollama", lambda: "C:/ollama.exe")
    monkeypatch.setattr(server, "start_ollama", lambda exe: started.append(exe))
    monkeypatch.setattr(OllamaClient, "version", lambda self: "0.12.0" if started else (_ for _ in ()).throw(
        __import__("triagesim.llm.base", fromlist=["ModelError"]).ModelError("down")))
    assert api.post("/api/ollama/start").json() == {"started": True, "version": "0.12.0"}
    assert started == ["C:/ollama.exe"]


def test_model_catalog(api, monkeypatch):
    import triagesim.server.app as server
    monkeypatch.setattr(server, "detect_gpus", lambda: [{"name": "RTX", "memory_gb": 16.0}])
    cat = api.get("/api/model-catalog").json()
    assert set(cat["tiers"]) == {"laptop", "gpu16", "gpu24", "gpu48", "embedding"}
    by_name = {m["name"]: m for m in cat["models"]}
    assert by_name["qwen2.5:7b"]["fits_gpu"] and not by_name["qwen2.5:32b"]["fits_gpu"]
    assert not any("cloud" in m["name"] for m in cat["models"])


def test_case_build_names_missing_files(api, app_dirs):
    (app_dirs[0] / "ed/medrecon.csv.gz").unlink()
    name = api.post("/api/cohorts", json=next(p for p in api.get("/api/cohort-presets").json()
                                              if p["name"] == "elderly_falls")["settings"]).json()["name"]
    r = api.post(f"/api/cohorts/{name}/cases")
    assert r.status_code == 400 and "data/ed/medrecon.csv.gz" in r.json()["detail"]


def test_cloud_models_are_rejected(api):
    preset = next(p for p in api.get("/api/experiment-presets").json() if p["name"] == "interview")
    config = preset["config"]
    config["nurse"]["model"]["name"] = "gpt-oss:120b-cloud"
    out = api.post("/api/experiments/validate", json=config).json()
    assert not out["valid"] and any("cloud model" in e for e in out["errors"])


def test_install_outside_windows_returns_the_command(api, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "platform", "linux")
    r = api.post("/api/ollama/install")
    assert r.status_code == 400 and "install.sh" in r.json()["detail"]


def test_terminal_log_tells_the_story(api, capsys):
    preset = next(p for p in api.get("/api/cohort-presets").json() if p["name"] == "elderly_falls")
    name = api.post("/api/cohorts", json=preset["settings"]).json()["name"]
    wait_job(api, api.post(f"/api/cohorts/{name}/cases").json()["id"])
    out = capsys.readouterr().out
    assert "Building cohort 'elderly_falls'" in out and "First qualifying visit per patient" in out
    assert "Cohort saved" in out and "Case files saved" in out


def test_run_with_missing_model_is_refused_before_starting(api, monkeypatch):
    from triagesim.llm.ollama import OllamaClient
    monkeypatch.setattr(OllamaClient, "list_models", lambda self: [{"name": "qwen2.5:7b", "size": 1, "modified": ""}])
    name = cohort_with_cases(api)
    preset = next(p for p in api.get("/api/experiment-presets").json() if p["name"] == "chart_review")
    config = preset["config"] | {"cohort": name}
    r = api.post("/api/runs", json=config)
    assert r.status_code == 400 and "qwen2.5:32b" in r.json()["detail"]
    config["nurse"]["model"]["name"] = "qwen2.5:7b"
    assert "name" in api.post("/api/runs", json=config).json()
    assert api.get("/api/runs").json()[0]["experiment"] == "chart_review"


def test_client_errors_reach_the_terminal(api, capsys):
    api.post("/api/client-error", json={"message": "boom", "where": "/runs/x", "stack": "at Foo"})
    assert "Browser error on /runs/x: boom" in capsys.readouterr().out


def test_page_is_not_cached(api):
    r = api.get("/runs/anything")
    assert r.headers.get("cache-control") in ("no-store", None)   # None only when the front end is not built


def test_preferred_port():
    from triagesim.cli import _free_port
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        taken = s.getsockname()[1]
        assert _free_port(taken) != taken


def test_delete_model_endpoint(api, monkeypatch):
    from triagesim.llm.ollama import OllamaClient
    deleted = []
    monkeypatch.setattr(OllamaClient, "delete", lambda self, name: deleted.append(name))
    assert api.delete("/api/models/llama3.2:3b").json() == {"deleted": "llama3.2:3b"}
    assert deleted == ["llama3.2:3b"]


def test_run_started_elsewhere_shows_as_running(api, tmp_path):
    """A run executed by a Slurm job (not by this app) is 'running' while its heartbeat is fresh."""
    import json as _json
    from triagesim.experiment.runner import write_status
    name = cohort_with_cases(api)
    preset = next(p for p in api.get("/api/experiment-presets").json() if p["name"] == "chart_review")
    run = api.post("/api/runs", json=demo(preset["config"]) | {"cohort": name}).json()["name"]
    wait_job(api, run)
    from triagesim import paths
    d = paths.runs_dir() / run
    write_status(d, state="running", heartbeat=time.time(), slurm_job="12345")
    api_jobs = __import__("triagesim.server.app", fromlist=["jobs"]).jobs
    api_jobs._jobs.pop(run, None)                      # as if another process ran it
    st = api.get(f"/api/runs/{run}").json()["status"]
    assert st["state"] == "running" and st["external"]
    r = api.post(f"/api/runs/{run}/stop")
    assert r.status_code == 409 and "scancel 12345" in r.json()["detail"]
    write_status(d, heartbeat=time.time() - 600)
    assert api.get(f"/api/runs/{run}").json()["status"]["state"] == "interrupted"


def test_access_token_required_when_set(api, monkeypatch):
    monkeypatch.setenv("TRIAGESIM_ACCESS_TOKEN", "s3cret")
    assert api.get("/api/ping").status_code == 200             # launcher check stays open
    assert api.get("/api/health").status_code == 401
    assert api.get("/api/cohorts?token=wrong").status_code == 401
    first = api.get("/?token=s3cret", follow_redirects=False)
    assert first.status_code == 303 and "token" not in first.headers["location"]
    assert api.get("/api/cohorts").status_code == 200          # cookie from the first visit
    api.cookies.clear()
    assert api.get("/api/cohorts").status_code == 401


def test_no_token_means_open_locally(api, monkeypatch):
    monkeypatch.delenv("TRIAGESIM_ACCESS_TOKEN", raising=False)
    assert api.get("/api/cohorts").status_code == 200


def test_runs_list_shows_type_and_models(api):
    name = cohort_with_cases(api)
    preset = next(p for p in api.get("/api/experiment-presets").json() if p["name"] == "interview")
    config = demo(preset["config"]) | {"cohort": name}
    config["patient"]["persona"] = "random"
    wait_job(api, api.post("/api/runs", json=config).json()["name"])
    row = api.get("/api/runs").json()[0]
    assert row["type"] == "Interview · random personas" and row["cohort"] == name
    assert row["models"] == {"nurse": "qwen2.5:32b", "patient": "llama3.1:8b", "evaluator": "qwen2.5:32b"}


def test_delete_run_and_cohort(api):
    """Deleting asks the server; running runs and cohorts in use by them are protected."""
    from triagesim import paths
    from triagesim.experiment.runner import write_status
    name = cohort_with_cases(api)
    preset = next(p for p in api.get("/api/experiment-presets").json() if p["name"] == "chart_review")
    run = api.post("/api/runs", json=demo(preset["config"]) | {"cohort": name}).json()["name"]
    wait_job(api, run)
    assert api.get("/api/runs").json()[0]["models"] == {"nurse": "qwen2.5:32b", "patient": None, "evaluator": None}
    assert api.get(f"/api/cohorts/{name}/runs").json() == [{"name": run, "active": False}]

    # a run still going elsewhere (Slurm) cannot be deleted, nor can its cohort
    write_status(paths.runs_dir() / run, state="running", heartbeat=time.time(), slurm_job="777")
    __import__("triagesim.server.app", fromlist=["jobs"]).jobs._jobs.pop(run, None)
    r = api.delete(f"/api/runs/{run}")
    assert r.status_code == 409 and "scancel 777" in r.json()["detail"]
    assert api.delete(f"/api/cohorts/{name}").status_code == 409

    write_status(paths.runs_dir() / run, state="stopped")
    assert api.delete(f"/api/runs/{run}").json() == {"deleted": run}
    assert not (paths.runs_dir() / run).exists() and api.get("/api/runs").json() == []
    assert api.delete(f"/api/cohorts/{name}").json() == {"deleted": name}
    assert api.get("/api/cohorts").json() == []
    assert api.delete(f"/api/cohorts/{name}").status_code == 404
    assert api.delete("/api/runs/..%2F..").status_code in (404, 405)   # never reaches a folder
    assert api.delete("/api/runs/no-such-run").status_code == 404
