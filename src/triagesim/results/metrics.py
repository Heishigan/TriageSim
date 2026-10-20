"""Metrics for one run and comparisons between runs. Pure Python, no SciPy needed.

Conventions (ESI 1 = most urgent):
  agreement      final ESI equals the triage nurse's ESI
  under-triage   final ESI is LESS urgent (a higher number) than the nurse's
  over-triage    final ESI is MORE urgent (a lower number)
Undecided cases are reported separately and excluded from the rates.
"""
from __future__ import annotations

import math
from statistics import mean, median, pstdev

Z95 = 1.959963984540054


def wilson(successes: int, n: int) -> dict:
    """Proportion with a 95% Wilson score interval, in percent."""
    if n == 0:
        return {"n": 0, "k": 0, "pct": None, "low": None, "high": None}
    p = successes / n
    denom = 1 + Z95 ** 2 / n
    centre = (p + Z95 ** 2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n * n)) / denom
    return {"n": n, "k": successes, "pct": round(100 * p, 1),
            "low": round(100 * max(0.0, centre - half), 1), "high": round(100 * min(1.0, centre + half), 1)}


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def weighted_kappa(pairs: list[tuple[int, int]], levels=range(1, 6)) -> float | None:
    """Quadratic-weighted Cohen's kappa between two raters."""
    levels = list(levels)
    n = len(pairs)
    if n == 0:
        return None
    k = len(levels)
    idx = {v: i for i, v in enumerate(levels)}
    observed = [[0.0] * k for _ in range(k)]
    for a, b in pairs:
        observed[idx[a]][idx[b]] += 1
    row = [sum(r) for r in observed]
    col = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    w = [[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)]
    num = sum(w[i][j] * observed[i][j] for i in range(k) for j in range(k))
    den = sum(w[i][j] * row[i] * col[j] / n for i in range(k) for j in range(k))
    return None if den == 0 else round(1 - num / den, 3)


def _mean_sd(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"mean": round(mean(values), 2), "sd": round(pstdev(values), 2), "n": len(values)}


def run_metrics(results: list[dict]) -> dict:
    """All metrics for one run."""
    decided = [r for r in results if r["esi"] is not None and r["reference_esi"] is not None]
    n = len(decided)
    under = [r for r in decided if r["esi"] > r["reference_esi"]]
    over = [r for r in decided if r["esi"] < r["reference_esi"]]
    agree = [r for r in decided if r["esi"] == r["reference_esi"]]
    within1 = [r for r in decided if abs(r["esi"] - r["reference_esi"]) <= 1]

    confusion = {str(ref): {str(got): 0 for got in range(1, 6)} for ref in range(1, 6)}
    for r in decided:
        confusion[str(r["reference_esi"])][str(r["esi"])] += 1

    head = [r for r in decided if r.get("head_injury") is True]
    labelled = any(r.get("head_injury") is not None for r in results)

    scores = {k: _mean_sd([r["evaluation"]["scores"][k] for r in results if r.get("evaluation")])
              for k in ("history_taking", "risk_identification", "decision")}

    personas: dict[str, dict] = {}
    for name in sorted({r["persona"] for r in decided if r.get("persona")}):
        group = [r for r in decided if r.get("persona") == name]
        personas[name] = {"cases": len(group),
                          "agreement": wilson(sum(r["esi"] == r["reference_esi"] for r in group), len(group)),
                          "under_triage": wilson(sum(r["esi"] > r["reference_esi"] for r in group), len(group))}

    questions = [r["questions"] for r in results if r.get("mode") == "interview" and r["decided"]]
    return {
        "cases": len(results),
        "decided": n,
        "undecided": len(results) - n,
        "forced_decisions": sum(bool(r.get("forced")) for r in results),
        "format_failures": sum(r.get("format_failures", 0) for r in results),
        "context_full_cases": sum(1 for r in results if r.get("context_full")),
        "agreement": wilson(len(agree), n),
        "within_one_level": wilson(len(within1), n),
        "under_triage": wilson(len(under), n),
        "over_triage": wilson(len(over), n),
        "weighted_kappa": weighted_kappa([(r["reference_esi"], r["esi"]) for r in decided]),
        "confusion": confusion,
        "head_injury": None if not labelled else {
            "cases": len(head),
            "under_triage_vs_nurse": wilson(sum(r["esi"] > r["reference_esi"] for r in head), len(head)),
            "esi_3_or_lower_urgency": wilson(sum(r["esi"] >= 3 for r in head), len(head)),
        },
        "questions": None if not questions else {"mean": round(mean(questions), 2), "median": median(questions),
                                                 "min": min(questions), "max": max(questions)},
        "evaluator_scores": scores,
        "by_persona": personas,
        "seconds_per_case": round(mean(r["seconds"] for r in results), 1) if results else None,
    }


OUTCOMES = {
    "under_triage": lambda r: r["esi"] > r["reference_esi"],
    "agreement": lambda r: r["esi"] == r["reference_esi"],
    "head_injury_under_triage": lambda r: r["esi"] > r["reference_esi"],
}


def compare_runs(a: list[dict], b: list[dict], outcome: str = "under_triage") -> dict:
    """Paired comparison on the cases both runs decided (exact McNemar)."""
    test = OUTCOMES[outcome]
    by_id = {r["case_id"]: r for r in b}
    pairs = [(r, by_id[r["case_id"]]) for r in a if r["case_id"] in by_id]
    pairs = [(x, y) for x, y in pairs if x["esi"] is not None and y["esi"] is not None]
    if outcome == "head_injury_under_triage":
        pairs = [(x, y) for x, y in pairs if x.get("head_injury") is True]
    only_a = sum(test(x) and not test(y) for x, y in pairs)
    only_b = sum(test(y) and not test(x) for x, y in pairs)
    return {"outcome": outcome, "paired_cases": len(pairs),
            "a": wilson(sum(test(x) for x, _ in pairs), len(pairs)),
            "b": wilson(sum(test(y) for _, y in pairs), len(pairs)),
            "only_a": only_a, "only_b": only_b, "p_value": round(mcnemar_exact(only_a, only_b), 4)}
