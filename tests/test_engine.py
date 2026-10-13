"""The conversation engine with scripted fake models (no GPU, fully predictable)."""
import json

import pytest

from triagesim.cases.build import CaseSettings, build_cases
from triagesim.cohort.build import build_cohort
from triagesim.cohort.settings import CohortSettings
from triagesim.experiment.config import ExperimentConfig
from triagesim.experiment.engine import Stopped, run_case
from triagesim.llm.fake import FakeModel


@pytest.fixture
def case(tables, case_tables, notes):
    cohort = build_cohort(tables, CohortSettings.from_yaml("configs/cohorts/elderly_falls.yaml")).cohort
    return build_cases(cohort, case_tables, notes, CaseSettings())[0][0]


def config(name, **changes):
    c = ExperimentConfig.from_yaml(f"configs/experiments/{name}.yaml")
    data = c.model_dump()
    for path, value in changes.items():
        target = data
        *parents, last = path.split(".")
        for p in parents:
            target = target[p]
        target[last] = value
    return ExperimentConfig.model_validate(data)


def doctor(nurse_turns):
    """One fake model for nurse and evaluator (they share qwen in the presets)."""
    turns = iter(nurse_turns)

    def reply(messages):
        system, last = messages[0].content, messages[-1].content
        if "attending emergency physician" in system:
            return json.dumps({"history_taking": 7, "risk_identification": 6, "decision": 8, "feedback": "ok"})
        return next(turns)
    return FakeModel("qwen2.5:32b", reply)


ASK = lambda q: json.dumps({"action": "ask", "message": q, "esi": None})
DECIDE = lambda e: json.dumps({"action": "decide", "message": f"ESI {e} because of the fall.", "esi": e})


def models(nurse, patient_replies=("I tripped on a rug.",)):
    return {"qwen2.5:32b": nurse, "llama3.1:8b": FakeModel("llama3.1:8b", list(patient_replies))}


def test_interview_flow_and_events(case):
    events = []
    nurse = doctor([ASK("Did you hit your head?"), ASK("Blood thinners?"), DECIDE(3)])
    patient = FakeModel("llama3.1:8b", ["I tripped on a rug.", "Yes, my forehead.", "Apixaban."])
    r = run_case(case, config("interview"), {"qwen2.5:32b": nurse, "llama3.1:8b": patient}, emit=events.append)
    speakers = [m["speaker"] for m in r["transcript"]]
    assert speakers == ["nurse", "patient", "nurse", "patient", "nurse", "patient", "nurse"]
    assert r["esi"] == 3 and r["decided"] and not r["forced"]
    assert r["questions"] == 3 and r["reference_esi"] == 2 and r["head_injury"] is True
    assert r["evaluation"]["scores"] == {"history_taking": 7, "risk_identification": 6, "decision": 8}
    assert [e["type"] for e in events][:2] == ["case_start", "message"] and events[-1]["type"] == "case_done"
    # The patient model never saw the redacted results or any answer.
    patient_prompt = patient.calls[0][0].content
    assert "subdural" not in patient_prompt and "ESI" not in patient_prompt
    assert "Apixaban" in patient_prompt


def test_nurse_prompt_has_vitals_but_not_history(case):
    nurse = doctor([DECIDE(2)])
    run_case(case, config("interview"), models(nurse))
    system = nurse.calls[0][0].content
    assert "Heart rate: 80" in system and "tripped" not in system and '"action"' in system


def test_bad_format_is_retried_once(case):
    nurse = doctor(["I think ESI 2", DECIDE(2)])
    r = run_case(case, config("interview"), models(nurse))
    assert r["esi"] == 2 and r["format_retries"] == 1 and r["format_failures"] == 0


def test_two_bad_replies_force_a_decision(case):
    nurse = doctor(["nonsense", "still nonsense", json.dumps({"esi": 3, "reasoning": "forced"})])
    r = run_case(case, config("interview"), models(nurse))
    assert r["forced"] and r["esi"] == 3 and r["format_failures"] == 1


def test_question_limit_forces_a_decision(case):
    nurse = doctor([ASK("q1"), ASK("q2"), ASK("q3"), json.dumps({"esi": 3, "reasoning": "limit"})])
    r = run_case(case, config("interview", **{"nurse.max_turns": 3}), models(nurse))
    assert r["forced"] and r["questions"] == 3 and r["esi"] == 3
    assert any("limit of 3 questions" in m["text"] for m in r["transcript"])


def test_decision_goes_straight_to_the_evaluator(case):
    nurse = doctor([DECIDE(3)])
    r = run_case(case, config("interview"), models(nurse))
    assert r["esi"] == 3 and r["transcript"][-1]["decision"] == 3
    assert not any(m["speaker"] == "system" for m in r["transcript"])   # no extra review step
    assert "ESI 3" in nurse.calls[-1][0].content                         # the evaluator saw the decision


def test_chart_review_and_multiple_choice(case):
    chart = FakeModel("qwen2.5:32b", lambda m: json.dumps({"esi": 2, "reasoning": "r"}))
    r = run_case(case, config("chart_review"), {"qwen2.5:32b": chart})
    assert r["mode"] == "chart_review" and r["esi"] == 2 and r["questions"] == 0
    assert "tripped over a rug" in chart.calls[0][0].content          # the chart includes the HPI

    def mcq(messages):
        return json.dumps({"answer": "D", "reasoning": "r"})
    r = run_case(case, config("multiple_choice"), {"qwen2.5:32b": FakeModel("qwen2.5:32b", mcq)})
    assert r["esi"] == 4


def test_retrieval_patient_answers_from_retrieved_passages(case):
    def embed(texts):  # crude bag of words, enough to rank passages
        vocab = ["head", "rug", "apixaban", "medications", "fibrillation"]
        return [[t.lower().count(w) + 0.01 for w in vocab] for t in texts]
    nurse = doctor([ASK("What medications do you take?"), DECIDE(2)])
    patient = FakeModel("llama3.1:8b", ["I take apixaban."])
    r = run_case(case, config("retrieval_patient"), {"qwen2.5:32b": nurse, "llama3.1:8b": patient}, embed=embed)
    answer = [m for m in r["transcript"] if m["speaker"] == "patient"][1]
    assert any("Apixaban" in p for p in answer["retrieved"])
    assert "Facts:" in patient.calls[-1][0].content


def test_random_persona_is_reproducible(case):
    c = config("interview_personas")
    first = run_case(case, c, models(doctor([DECIDE(2)])))["persona"]
    again = run_case(case, c, models(doctor([DECIDE(2)])))["persona"]
    assert first == again and first in {"cooperative", "stoic", "anxious", "confused"}


def test_stop_interrupts_a_case(case):
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 2
    with pytest.raises(Stopped):
        run_case(case, config("interview"), models(doctor([ASK("q")] * 20)), should_stop=stop)
