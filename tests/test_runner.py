import json
import threading

import pytest

from triagesim.cases.build import CaseSettings, build_cases, save_cases
from triagesim.cohort.build import build_cohort
from triagesim.cohort.settings import CohortSettings
from triagesim.experiment.config import ExperimentConfig
from triagesim.experiment.runner import (create_run, execute, list_runs, read_results, read_status,
                                         resolve_cohort)
from triagesim.llm.base import ModelError
from triagesim.llm.demo import DemoModel


@pytest.fixture
def cohorts(tmp_path, tables, case_tables, notes):
    """A saved cohort 'elderly_falls_<stamp>' with two cases."""
    cohort = build_cohort(tables, CohortSettings.from_yaml("configs/cohorts/elderly_falls.yaml")).cohort
    folder = tmp_path / "cohorts" / "elderly_falls_20261013-090000"
    folder.mkdir(parents=True)
    cases, flow = build_cases(cohort, case_tables, notes, CaseSettings(require_hpi=False))
    save_cases(folder, cases, flow, CaseSettings())
    return tmp_path / "cohorts"


def demo_config(name="interview", **sampling):
    data = ExperimentConfig.from_yaml(f"configs/experiments/{name}.yaml").model_dump()
    for agent in ("nurse", "patient", "evaluator"):
        if data.get(agent):
            data[agent]["model"]["source"] = "demo"
    data["sampling"].update(sampling)
    return ExperimentConfig.model_validate(data)


def test_resolve_cohort_by_name(cohorts):
    assert resolve_cohort("elderly_falls", cohorts).name == "elderly_falls_20261013-090000"
    with pytest.raises(FileNotFoundError, match="Build the cohort"):
        resolve_cohort("other", cohorts)


def test_full_demo_run(cohorts, tmp_path):
    run_dir = create_run(demo_config(), tmp_path / "runs", cohorts)
    assert read_status(run_dir)["state"] == "created" and read_status(run_dir)["total"] == 2
    status = execute(run_dir)
    assert status["state"] == "completed" and status["done"] == 2
    results = read_results(run_dir)
    assert len(results) == 2 and all(r["decided"] for r in results)
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    assert sum(e["type"] == "case_done" for e in events) == 2
    assert list_runs(tmp_path / "runs") == [run_dir]


def test_stop_and_resume(cohorts, tmp_path):
    run_dir = create_run(demo_config(), tmp_path / "runs", cohorts)
    stop = threading.Event()

    def stop_after_first_case(event):
        if event["type"] == "case_done":
            stop.set()
    status = execute(run_dir, stop=stop, on_event=stop_after_first_case)
    assert status["state"] == "stopped" and status["done"] == 1
    status = execute(run_dir)                                     # resume
    assert status["state"] == "completed" and status["done"] == 2
    assert len({r["case_id"] for r in read_results(run_dir)}) == 2  # no case ran twice


def test_model_failure_marks_run_failed(cohorts, tmp_path):
    class Down:
        name = "x"

        def chat(self, *a, **k):
            raise ModelError("Ollama at http://localhost:11434 is not reachable")
    run_dir = create_run(demo_config(), tmp_path / "runs", cohorts)
    status = execute(run_dir, models={"qwen2.5:32b": Down(), "llama3.1:8b": DemoModel()})
    assert status["state"] == "failed" and "not reachable" in status["error"]


def test_sampling_is_reproducible(cohorts, tmp_path):
    a = create_run(demo_config(cases=1, seed=7), tmp_path / "runs", cohorts)
    b = create_run(demo_config(cases=1, seed=7), tmp_path / "runs", cohorts)
    assert json.loads((a / "plan.json").read_text())["case_ids"] == json.loads((b / "plan.json").read_text())["case_ids"]


@pytest.mark.parametrize("preset", ["interview_personas", "retrieval_patient", "chart_review", "multiple_choice"])
def test_every_preset_runs_with_the_demo_model(cohorts, tmp_path, preset):
    run_dir = create_run(demo_config(preset), tmp_path / "runs", cohorts)
    assert execute(run_dir)["state"] == "completed"


def test_results_from_before_self_review_removal_still_load(tmp_path):
    """Runs saved before 2026-10-13 have esi_initial/esi_final instead of esi."""
    from triagesim.results.metrics import run_metrics
    old = {"case_id": "case-00001", "reference_esi": 2, "esi_initial": 3, "esi_final": 2, "decided": True,
           "forced": False, "head_injury": None, "persona": None, "mode": "chart_review", "questions": 0,
           "format_failures": 0, "seconds": 1.0, "evaluation": None}
    (tmp_path / "results.jsonl").write_text(json.dumps(old) + "\n")
    results = read_results(tmp_path)
    assert results[0]["esi"] == 2
    assert run_metrics(results)["agreement"]["k"] == 1


def test_heartbeat_tells_running_from_gone(cohorts, tmp_path, monkeypatch):
    import time as _time
    from triagesim.experiment import runner
    from triagesim.experiment.runner import is_alive, write_status
    assert is_alive({"heartbeat": _time.time()})
    assert not is_alive({"heartbeat": _time.time() - 600}) and not is_alive({})
    monkeypatch.setattr(runner, "HEARTBEAT_SECONDS", 0.05)
    run_dir = create_run(demo_config(), tmp_path / "runs", cohorts)
    beats = []

    def slow(event):
        if event["type"] == "case_done":
            _time.sleep(0.2)
            beats.append(read_status(run_dir).get("heartbeat"))
    execute(run_dir, on_event=slow)
    assert beats and all(b for b in beats)
    assert read_status(run_dir)["host"]
