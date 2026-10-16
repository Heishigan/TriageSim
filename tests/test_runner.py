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


@pytest.mark.parametrize("preset", ["interview", "chart_review", "multiple_choice"])
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


def _cases(levels: dict[int, int], hi_every: int | None = None) -> list[dict]:
    out, n = [], 0
    for esi, count in levels.items():
        for i in range(count):
            n += 1
            hi = None if hi_every is None else i % hi_every == 0
            out.append({"case_id": f"case-{n:05d}", "reference": {"esi": esi, "head_injury_icd": hi},
                        "nurse_view": {"age": 80, "sex": "F", "vitals": {"heartrate": 80}},
                        "patient_view": {"hpi": "fell", "medications": []}, "audit": {}})
    return out


def test_allocation_keeps_the_cohort_mix():
    from triagesim.experiment.runner import allocate
    cohort = {1: 633, 2: 3811, 3: 2970, 4: 61}            # the ESI mix of the falls cohort
    pool = {1: 500, 2: 2900, 3: 2300, 4: 50}
    a = allocate(1000, cohort, pool)
    assert sum(a.values()) == 1000
    assert a == {1: 85, 2: 510, 3: 397, 4: 8}               # 8.5 / 51.0 / 39.7 / 0.8 %
    assert sum(allocate(20, cohort, pool).values()) == 20
    short = allocate(1000, cohort, {1: 10, 2: 2900, 3: 2300, 4: 50})   # too few ESI 1 cases
    assert short[1] == 10 and sum(short.values()) == 1000


def test_stratified_sample_is_reproducible_and_interleaved():
    from triagesim.experiment.runner import sample_case_ids
    cases = _cases({1: 100, 2: 600, 3: 470, 4: 10})
    config = demo_config(cases=200, order="stratified", seed=42, stratify_head_injury=False)
    target = {1: 633, 2: 3811, 3: 2970, 4: 61}
    ids = sample_case_ids(cases, config, target)
    assert ids == sample_case_ids(cases, config, target) and len(set(ids)) == 200
    esi = {c["case_id"]: c["reference"]["esi"] for c in cases}
    counts = {k: sum(esi[i] == k for i in ids) for k in (1, 2, 3, 4)}
    assert counts == {1: 17, 2: 102, 3: 79, 4: 2}
    first_half = [esi[i] for i in ids[:100]]
    assert 30 <= first_half.count(2) <= 70                  # levels are mixed, not in blocks
    other = sample_case_ids(cases, demo_config(cases=200, order="stratified", seed=7, stratify_head_injury=False), target)
    assert set(other) != set(ids)


def test_stratified_run_records_the_mix(cohorts, tmp_path):
    run_dir = create_run(demo_config(cases=1, order="stratified"), tmp_path / "runs", cohorts)
    plan = json.loads((run_dir / "plan.json").read_text())
    sample = plan["sample"]
    assert sample["flow"]["sample"] == 1 and sum(r["sample"] for r in sample["esi"]) == 1
    assert sample["ok"] and len(sample["sample_id"]) == 10


def test_head_injury_share_is_kept_within_each_esi_level():
    from triagesim.experiment.runner import describe_sample, sample_case_ids
    cases = _cases({1: 100, 2: 600, 3: 470, 4: 10}, hi_every=5)     # 20% head injuries in every level
    config = demo_config(cases=500, order="stratified", seed=42, stratify_head_injury=True)
    target = {1: 633, 2: 3811, 3: 2970, 4: 61}
    ids = sample_case_ids(cases, config, target)
    summary = describe_sample(cases, ids, target, config)
    assert summary["flow"]["sample"] == 500 and summary["ok"]
    assert summary["head_injury"]["sample"] == 100                    # exactly 20%
    assert [r["sample"] for r in summary["esi"]] == [42, 255, 199, 4]
    assert all(c["level"] in ("ok", "info") for c in summary["checks"])
    # without the label the option is refused with a clear message
    with pytest.raises(ValueError, match="head-injury label"):
        sample_case_ids(_cases({2: 1000}), config, {2: 1})


def test_summary_flags_problems():
    from triagesim.experiment.runner import describe_sample
    cases = _cases({2: 10, 3: 10}, hi_every=2)
    cases[0]["patient_view"]["hpi"] = ""
    config = demo_config(cases=50, order="random")
    ids = [c["case_id"] for c in cases]
    summary = describe_sample(cases, ids, {2: 50, 3: 50}, config)
    texts = " ".join(c["text"] for c in summary["checks"])
    assert "only 20 have an ESI" in texts and "1 sampled cases have no history" in texts
    assert describe_sample(cases, ids + ids[:1], {2: 50, 3: 50}, config)["ok"] is False   # duplicate
