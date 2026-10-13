import pytest

from triagesim.results.metrics import compare_runs, mcnemar_exact, run_metrics, weighted_kappa, wilson


def r(case, ref, final, initial=None, head=None, persona=None, mode="interview", questions=4, scores=None):
    return {"case_id": case, "reference_esi": ref, "esi_final": final,
            "esi_initial": final if initial is None else initial, "head_injury": head, "persona": persona,
            "mode": mode, "questions": questions, "decided": final is not None, "forced": False,
            "format_failures": 0, "seconds": 2.0,
            "evaluation": {"scores": scores} if scores else None}


def test_wilson_matches_known_values():
    # 28.4% of 394 was a thesis value: 112/394 -> 24.2-33.1
    w = wilson(112, 394)
    assert (w["pct"], w["low"], w["high"]) == (28.4, 24.2, 33.1)
    assert wilson(0, 0)["pct"] is None


def test_mcnemar_exact():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(10, 0) == pytest.approx(0.001953125)
    assert mcnemar_exact(5, 5) == 1.0


def test_weighted_kappa():
    assert weighted_kappa([(1, 1), (2, 2), (3, 3), (4, 4)]) == 1.0
    assert weighted_kappa([]) is None


def test_run_metrics():
    results = [r("a", 2, 2, head=True, persona="stoic", scores={"history_taking": 8, "risk_identification": 6,
                                                                  "decision": 7}),
               r("b", 2, 3, initial=4, head=True, persona="stoic"),
               r("c", 3, 2, head=False, persona="anxious"),
               r("d", 3, None, head=False)]
    m = run_metrics(results)
    assert m["cases"] == 4 and m["decided"] == 3 and m["undecided"] == 1
    assert m["agreement"]["k"] == 1 and m["under_triage"]["k"] == 1 and m["over_triage"]["k"] == 1
    assert m["head_injury"]["cases"] == 2 and m["head_injury"]["under_triage_vs_nurse"]["k"] == 1
    assert m["head_injury"]["esi_3_or_lower_urgency"]["k"] == 1
    assert m["self_review"]["changed"] == 1 and m["self_review"]["more_urgent"] == 1
    assert m["confusion"]["2"]["3"] == 1
    assert m["evaluator_scores"]["history_taking"] == {"mean": 8, "sd": 0, "n": 1}
    assert m["by_persona"]["stoic"]["cases"] == 2


def test_no_labels_gives_no_head_injury_block():
    assert run_metrics([r("a", 2, 2)])["head_injury"] is None


def test_compare_runs_is_paired():
    a = [r("x", 2, 3), r("y", 2, 3), r("z", 2, 2)]
    b = [r("x", 2, 2), r("y", 2, 3), r("z", 2, 2), r("extra", 2, 4)]
    c = compare_runs(a, b)
    assert c["paired_cases"] == 3 and c["only_a"] == 1 and c["only_b"] == 0 and c["p_value"] == 1.0
