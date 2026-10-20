"""The retrieved-similar-cases ablation: fixed pool, no leakage, deterministic retrieval."""
import json
from pathlib import Path

import pytest

from triagesim.experiment.config import ExperimentConfig
from triagesim.experiment.runner import create_run, execute, read_results
from triagesim.experiment.similar import SimilarCases, build_pool, pool_id, render_examples
from triagesim.llm.demo import demo_embed

from test_runner import cohorts, demo_config  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]


def _case(cid, subject, complaint, hr, esi):
    return {"case_id": cid, "subject_id": subject, "reference": {"esi": esi},
            "nurse_view": {"age": 80, "sex": "F", "chief_complaint": complaint, "arrival_transport": "AMBULANCE",
                           "vitals": {"temperature": 98.0, "heartrate": hr, "resprate": 16, "o2sat": 98,
                                      "sbp": 130, "dbp": 70, "pain": 2}},
            "patient_view": {}}


def test_pool_leaves_out_sampled_cases_and_their_patients():
    cases = [_case("c1", 1, "fall", 80, 2), _case("c2", 1, "fall", 80, 3), _case("c3", 2, "fall", 80, 2),
             _case("c4", 3, "hip pain", 80, None)]
    pool = build_pool(cases, ["c1"])
    assert [c["case_id"] for c in pool] == ["c3"]      # c2: same patient as c1; c4: no ESI
    assert pool_id(["b", "a"]) == pool_id(["a", "b"])


def test_retrieval_by_complaint_then_vitals_is_deterministic():
    pool = [_case(f"p{i}", 10 + i, c, hr, 3) for i, (c, hr) in enumerate(
        [("head strike fall", 80), ("head strike fall", 130), ("hip pain", 80), ("fall head", 75)])]
    query = _case("q", 1, "fall head strike", 78, 2)
    index = SimilarCases(pool, [query], demo_embed)
    got = [c["case_id"] for c in index.retrieve(query, k=2, candidates_per_example=1)]
    assert got == [c["case_id"] for c in index.retrieve(query, k=2, candidates_per_example=1)]
    assert "p2" not in got                               # hip pain: not similar by complaint
    assert index.retrieve(query, k=1, candidates_per_example=3)[0]["case_id"] != "p1"   # closest vitals first
    text = render_examples(index.retrieve(query, k=2, candidates_per_example=2))
    assert text.count("Triage nurse's ESI: 3") == 2 and "head" in text


def test_embeddings_are_cached_for_resume(tmp_path):
    pool, query = [_case("p1", 2, "fall", 80, 3)], _case("q", 1, "fall", 80, 2)
    calls = []

    def embed(texts):
        calls.append(len(texts))
        return demo_embed(texts)
    SimilarCases(pool, [query], embed, cache=tmp_path / "e.json")
    SimilarCases(pool, [query], embed, cache=tmp_path / "e.json")
    assert len(calls) == 1


def test_config_rules():
    data = ExperimentConfig.from_yaml(ROOT / "configs/experiments/main/main_similar_qwen38.yaml").model_dump()
    bad = json.loads(json.dumps(data)); bad["nurse"]["similar_cases"] = None
    with pytest.raises(ValueError):
        ExperimentConfig.model_validate(bad)
    bad = json.loads(json.dumps(data)); bad["nurse"]["mode"] = "multiple_choice"
    with pytest.raises(ValueError):
        ExperimentConfig.model_validate(bad)


def test_similar_ablation_differs_from_chart_review_only_by_the_examples():
    chart = ExperimentConfig.from_yaml(ROOT / "configs/experiments/main/main_chart_qwen38.yaml")
    for name, cases, seed in (("main_similar_qwen38", 1000, 42), ("pilot_similar_qwen38", 20, 7)):
        sim = ExperimentConfig.from_yaml(ROOT / f"configs/experiments/main/{name}.yaml")
        added = [l for l in sim.nurse.system_prompt.split("\n") if l not in chart.nurse.system_prompt.split("\n")]
        assert len(added) == 2 and added[0].startswith("Similar earlier patients") and added[1] == "{similar_cases}"
        assert sim.nurse.sees == chart.nurse.sees + ["similar_cases"]
        assert sim.nurse.similar_cases.k == 40 and sim.nurse.model.num_ctx == 32768
        assert sim.nurse.model.model_copy(update={"num_ctx": None}) == chart.nurse.model
        assert (sim.sampling.cases, sim.sampling.seed) == (cases, seed) and sim.cohort == chart.cohort


def test_run_with_similar_cases_never_shows_a_sampled_case(cohorts, tmp_path):  # noqa: F811
    data = demo_config("chart_review", cases=1).model_dump()
    data["nurse"]["sees"].append("similar_cases")
    data["nurse"]["similar_cases"] = {"k": 5}
    data["nurse"]["system_prompt"] += "\nSimilar patients:\n{similar_cases}\n"
    run_dir = create_run(ExperimentConfig.model_validate(data), tmp_path / "runs", cohorts)
    plan = json.loads((run_dir / "plan.json").read_text())
    pool = json.loads((run_dir / "pool.json").read_text())
    assert plan["similar_cases_pool"]["pool_id"] == pool["pool_id"]
    assert not set(pool["case_ids"]) & set(plan["case_ids"])
    assert execute(run_dir)["state"] == "completed"
    result = read_results(run_dir)[0]
    assert result["similar_case_ids"] and not set(result["similar_case_ids"]) & set(plan["case_ids"])
    assert set(result["similar_case_ids"]) <= set(pool["case_ids"])
    assert (run_dir / "pool_embeddings.json").is_file()


def test_ties_at_the_cutoff_all_reach_the_vitals_step():
    # 10 identical complaints; with k=2 x 1 the old code kept p0, p1 by case number only.
    pool = [_case(f"p{i}", 10 + i, "fall", 60 + 10 * i, 3) for i in range(10)]
    query = _case("q", 1, "fall", 150, 2)
    index = SimilarCases(pool, [query], demo_embed)
    got = [c["case_id"] for c in index.retrieve(query, k=2, candidates_per_example=1)]
    assert got == ["p9", "p8"]                      # closest heart rates, from the whole tied group


def test_most_similar_example_is_listed_last():
    a, b = _case("a", 2, "fall", 80, 2), _case("b", 3, "fall", 80, 3)
    text = render_examples([a, b]).split("\n")       # a is the most similar
    assert text[-1].endswith("ESI: 2") and text[0].endswith("ESI: 3")


def test_a_failed_embedding_batch_is_retried(monkeypatch):
    from triagesim.experiment import similar
    from triagesim.llm.base import ModelError
    monkeypatch.setattr(similar, "EMBED_RETRY_WAITS", (0, 0))
    calls = []

    def flaky(texts):
        calls.append(1)
        if len(calls) == 1:
            raise ModelError("worker stopped")
        return demo_embed(texts)
    SimilarCases([_case("p1", 2, "fall", 80, 3)], [_case("q", 1, "hip pain", 80, 2)], flaky)
    assert len(calls) == 2


def test_context_window_is_sent_and_a_full_window_is_flagged(cohorts, tmp_path):  # noqa: F811
    from triagesim.llm.demo import DemoModel
    from triagesim.llm.base import ChatResult
    seen = []

    class Tight(DemoModel):
        def chat(self, messages, **kw):
            seen.append(kw.get("num_ctx"))
            r = super().chat(messages, **kw)
            return ChatResult(content=r.content, model=r.model, prompt_tokens=990, completion_tokens=20, seconds=0)
    data = demo_config("chart_review", cases=1).model_dump()
    data["nurse"]["model"]["num_ctx"] = 1000
    run_dir = create_run(ExperimentConfig.model_validate(data), tmp_path / "runs", cohorts)
    execute(run_dir, models={"qwen2.5:32b": Tight("qwen2.5:32b")})
    result = read_results(run_dir)[0]
    assert seen and set(seen) == {1000}
    assert result["context_full"] == 1 and result["max_prompt_tokens"]["nurse"] == 990
