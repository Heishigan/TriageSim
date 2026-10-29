"""Statistics for the paper, aggregate only (no case ids, no patient text).

    uv run --frozen --with scipy==1.18.1 --with pingouin==0.7.0 python paper/paper_stats.py > outputs/paper_stats.json

Follows the analysis plan in the Methods:
  * proportions over all 1000 cases with 95% Wilson intervals; a case without a decision
    counts as under-triaged (and not as agreement);
  * quadratic weighted kappa with a 95% percentile bootstrap interval (10000 resamples of cases);
  * paired differences between conditions with 95% Newcombe (1998, method 10) intervals;
  * binary outcomes (under-triage, the primary outcome; agreement; over-triage; within one level;
    and under-triage and agreement in the head-injury subgroup) compared across the six conditions
    with Cochran's Q, then all 15 pairs with the McNemar mid-p test, Bonferroni-adjusted (x15)
    within each outcome; effect size = share of discordant cases in which condition A had the
    outcome (0.5 = no difference), alongside the Newcombe difference;
  * questions and evaluator scores (interview vs interview with personas, paired by case):
    medians with interquartile ranges, Shapiro-Wilk on the paired differences, Wilcoxon
    signed-rank test with matched-pairs rank-biserial correlation and CLES (pingouin).
"""
import json
import math
import sys

import numpy as np
import pingouin as pg
import scipy
from scipy import stats

from triagesim.experiment.runner import list_runs, read_results
from triagesim.results.metrics import wilson

CONDITIONS = {  # paper name -> run-name prefix
    "chart_review": "main_chart_qwen38_",
    "mcq": "main_mcq_qwen38_",
    "interview": "main_interview_qwen38_",
    "personas": "main_personas_qwen38_",
    "arrival_only": "main_arrival_qwen38_",
    "similar_cases": "main_similar_qwen38_",
}
ORDER = ["chart_review", "mcq", "arrival_only", "similar_cases", "interview", "personas"]  # Table 2 order
# all 15 pairs, condition A later in ORDER than condition B, grouped by B (Table 3 order)
PAIRS = [(ORDER[j], ORDER[i]) for i in range(len(ORDER)) for j in range(i + 1, len(ORDER))]
BINARY = ["under_triage", "agreement", "over_triage", "within_one"]
B = 10_000
RNG = np.random.default_rng(42)


def load():
    runs = {}
    for name, prefix in CONDITIONS.items():
        dirs = sorted(d for d in list_runs() if d.name.startswith(prefix))
        if not dirs:
            continue
        runs[name] = {r["case_id"]: r for r in read_results(dirs[-1])}
    return runs


def outcomes(r):
    esi, ref = r["esi"], r["reference_esi"]
    if esi is None:
        return {"agreement": 0, "under_triage": 1, "over_triage": 0, "within_one": 0, "decided": 0}
    return {"agreement": int(esi == ref), "under_triage": int(esi > ref), "over_triage": int(esi < ref),
            "within_one": int(abs(esi - ref) <= 1), "decided": 1}


def qwk(a, b, k=5):
    a = np.asarray(a) - 1
    b = np.asarray(b) - 1
    n = len(a)
    obs = np.zeros((k, k))
    np.add.at(obs, (a, b), 1)
    w = (np.subtract.outer(np.arange(k), np.arange(k)) ** 2) / (k - 1) ** 2
    exp = np.outer(obs.sum(1), obs.sum(0)) / n
    den = (w * exp).sum()
    return float(1 - (w * obs).sum() / den) if den else float("nan")


def kappa_ci(refs, got):
    refs, got = np.asarray(refs), np.asarray(got)
    n = len(refs)
    est = qwk(refs, got)
    boots = np.empty(B)
    for i in range(B):
        idx = RNG.integers(0, n, n)
        boots[i] = qwk(refs[idx], got[idx])
    lo, hi = np.nanpercentile(boots, [2.5, 97.5])
    return {"kappa": round(est, 3), "low": round(float(lo), 3), "high": round(float(hi), 3), "n": n}


def wilson_raw(k, n, z=1.959963984540054):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, c - h, c + h


def newcombe_paired(x, y):
    """Difference p_x - p_y for paired binary outcomes, Newcombe method 10."""
    x, y = np.asarray(x), np.asarray(y)
    n = len(x)
    a = int(((x == 1) & (y == 1)).sum()); b = int(((x == 1) & (y == 0)).sum())
    c = int(((x == 0) & (y == 1)).sum()); d = int(((x == 0) & (y == 0)).sum())
    p1, l1, u1 = wilson_raw(a + b, n)
    p2, l2, u2 = wilson_raw(a + c, n)
    den = math.sqrt((a + b) * (c + d) * (a + c) * (b + d))
    phi = (a * d - b * c) / den if den else 0.0
    diff = p1 - p2
    dl = math.sqrt(max(0.0, (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2))
    du = math.sqrt(max(0.0, (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2))
    return {"diff_pct": round(100 * diff, 1), "low": round(100 * (diff - dl), 1),
            "high": round(100 * (diff + du), 1), "b_only_first": b, "c_only_second": c, "n": n}


def mcnemar_midp(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    pmf = lambda i: math.comb(n, i) / 2 ** n  # noqa: E731
    exact = min(1.0, 2 * sum(pmf(i) for i in range(k + 1)))
    return exact - pmf(k)


def bonferroni(pvals):
    return [min(1.0, len(pvals) * p) for p in pvals]


def cochran_q(matrix):
    """Cochran's Q for a cases x conditions 0/1 matrix; returns Q, df, p (chi-squared)."""
    x = np.asarray(matrix, dtype=float)
    n, k = x.shape
    col, row = x.sum(0), x.sum(1)
    total = x.sum()
    den = k * total - (row ** 2).sum()
    q = (k - 1) * (k * (col ** 2).sum() - total ** 2) / den if den else 0.0
    return float(q), k - 1, float(stats.chi2.sf(q, k - 1))


def med_iqr(v):
    if not v:
        return None
    q1, m, q3 = np.percentile(v, [25, 50, 75])
    return {"median": float(m), "q1": float(q1), "q3": float(q3), "n": len(v)}


def main():
    runs = load()
    common = sorted(set.intersection(*(set(r) for r in runs.values())))
    out = {"n_cases": len(common), "conditions": {}, "paired": {}}
    O = {name: {cid: outcomes(runs[name][cid]) for cid in common} for name in runs}
    hi = [cid for cid in common if runs["chart_review"][cid]["head_injury"]]

    for name, res in runs.items():
        rows = [res[cid] for cid in common]
        o = [O[name][cid] for cid in common]
        dec = [r for r in rows if r["esi"] is not None]
        m = {k: wilson(sum(x[k] for x in o), len(o)) for k in ("agreement", "under_triage", "over_triage", "within_one")}
        m["undecided"] = len(rows) - len(dec)
        m["forced"] = sum(bool(r.get("forced")) for r in rows)
        m["format_failures"] = sum(r.get("format_failures", 0) > 0 for r in rows)
        m["context_full"] = sum(bool(r.get("context_full")) for r in rows)
        m["weighted_kappa"] = kappa_ci([r["reference_esi"] for r in dec], [r["esi"] for r in dec])
        m["assigned_esi"] = {str(l): sum(r["esi"] == l for r in dec) for l in range(1, 6)}
        m["confusion"] = {str(ref): {str(l): sum(r["reference_esi"] == ref and r["esi"] == l for r in dec)
                                     for l in range(1, 6)} for ref in range(1, 6)}  # nurse ESI -> assigned ESI
        m["under_triage_by_reference_esi"] = {
            str(l): wilson(sum(O[name][r["case_id"]]["under_triage"] for r in rows if r["reference_esi"] == l),
                           sum(r["reference_esi"] == l for r in rows)) for l in (1, 2, 3, 4)}
        m["head_injury"] = {k: wilson(sum(O[name][c][k] for c in hi), len(hi)) for k in ("under_triage", "agreement")}
        if any(r["mode"] == "interview" for r in rows):
            m["questions"] = med_iqr([r["questions"] for r in rows])
            ev = [r["evaluation"]["scores"] for r in rows if r.get("evaluation")]
            m["evaluator_scores"] = {k: med_iqr([s[k] for s in ev]) for k in ("history_taking", "risk_identification", "decision")}
        personas = sorted({r["persona"] for r in rows if r.get("persona")})
        if len(personas) > 1:
            m["by_persona"] = {p: {k: wilson(sum(O[name][r["case_id"]][k] for r in rows if r["persona"] == p),
                                             sum(r["persona"] == p for r in rows)) for k in ("under_triage", "agreement")}
                               for p in personas}
        out["conditions"][name] = m

    out["software"] = {"python": sys.version.split()[0], "numpy": np.__version__,
                       "scipy": scipy.__version__, "pingouin": pg.__version__}

    # binary outcomes: Cochran's Q over the six conditions, then McNemar mid-p for all 15 pairs
    out["omnibus"], out["posthoc"] = {}, {}
    sets = {"": common, "head_injury_": hi}
    for prefix, cases in sets.items():
        for k in BINARY:
            name = prefix + k
            q, df, p = cochran_q([[O[c][cid][k] for c in ORDER] for cid in cases])
            out["omnibus"][name] = {"test": "Cochran Q", "Q": round(q, 2), "df": df, "p": p, "n": len(cases)}
            rows = []
            for a, b in PAIRS:
                d = newcombe_paired([O[a][c][k] for c in cases], [O[b][c][k] for c in cases])
                disc = d["b_only_first"] + d["c_only_second"]
                rows.append({"a": a, "b": b, **d,
                             "discordant_share_a": round(d["b_only_first"] / disc, 3) if disc else None,
                             "p": mcnemar_midp(d["b_only_first"], d["c_only_second"])})
            for r, padj in zip(rows, bonferroni([r["p"] for r in rows])):
                r["p_bonferroni"] = padj
            out["posthoc"][name] = rows

    # Newcombe differences for all 15 pairs kept under the old key layout
    for a, b in PAIRS:
        key = f"{a}_vs_{b}"
        out["paired"][key] = {}
        for k in BINARY:
            out["paired"][key][k] = newcombe_paired([O[a][c][k] for c in common], [O[b][c][k] for c in common])
            out["paired"][key]["head_injury_" + k] = newcombe_paired([O[a][c][k] for c in hi], [O[b][c][k] for c in hi])

    # questions and evaluator scores: interview vs interview with personas, paired by case
    out["interview_vs_personas"] = {}
    ra, rb = runs["personas"], runs["interview"]
    measures = {"questions": lambda r: r["questions"]}
    for s_ in ("history_taking", "risk_identification", "decision"):
        measures[s_] = (lambda key: lambda r: r["evaluation"]["scores"][key] if r.get("evaluation") else None)(s_)
    for m_name, f in measures.items():
        pairs_ = [(f(ra[c]), f(rb[c])) for c in common]
        pairs_ = [(x, y) for x, y in pairs_ if x is not None and y is not None]
        x = np.array([p_[0] for p_ in pairs_], dtype=float)
        y = np.array([p_[1] for p_ in pairs_], dtype=float)
        sw = stats.shapiro(x - y)
        w = pg.wilcoxon(x, y)
        out["interview_vs_personas"][m_name] = {
            "a": "personas", "b": "interview", "n_pairs": len(x),
            "a_summary": med_iqr(list(x)), "b_summary": med_iqr(list(y)),
            "shapiro_W": round(float(sw.statistic), 3), "shapiro_p": float(sw.pvalue),
            "n_zero_differences": int((x == y).sum()),
            "wilcoxon_W": float(w["W_val"].iloc[0]), "p": float(w["p_val"].iloc[0]),
            "rank_biserial": round(float(w["RBC"].iloc[0]), 3), "cles": round(float(w["CLES"].iloc[0]), 3)}

    json.dump(out, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
