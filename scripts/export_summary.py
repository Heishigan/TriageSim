"""Write an aggregate-only summary of runs, safe to share (no patient text, no case ids).

    uv run --frozen python scripts/export_summary.py pilot_ > summary_pilot.json

The argument is a run-name prefix (default: all runs). For every matching run it writes the
settings (models, mode, persona, sampling, sample ID) and the same aggregate metrics as the
Results page, plus paired comparisons (exact McNemar) between runs that share a sample ID.
Nothing per case is written: no transcripts, evaluator feedback, case ids or labels.
"""
import itertools
import json
import sys

import yaml

from triagesim import paths
from triagesim.experiment.runner import list_runs, read_results, read_status
from triagesim.results.metrics import compare_runs, run_metrics

prefix = sys.argv[1] if len(sys.argv) > 1 else ""
runs = {}
for d in sorted(list_runs(), key=lambda p: p.name):
    if not d.name.startswith(prefix):
        continue
    cfg = yaml.safe_load((d / "experiment.yaml").read_text(encoding="utf-8")) or {}
    plan = json.loads((d / "plan.json").read_text()) if (d / "plan.json").is_file() else {}
    sample = plan.get("sample") or {}
    model = lambda agent: ((cfg.get(agent) or {}).get("model") or {}).get("name")  # noqa: E731
    results = read_results(d)
    runs[d.name] = {
        "state": read_status(d).get("state"),
        "mode": (cfg.get("nurse") or {}).get("mode"),
        "persona": (cfg.get("patient") or {}).get("persona") if (cfg.get("nurse") or {}).get("mode") == "interview" else None,
        "models": {"nurse": model("nurse"), "patient": model("patient"),
                   "evaluator": model("evaluator") if (cfg.get("evaluator") or {}).get("enabled") else None},
        "max_tokens": {a: ((cfg.get(a) or {}).get("model") or {}).get("max_tokens") for a in ("nurse", "patient", "evaluator")},
        "sampling": cfg.get("sampling"),
        "sample_id": sample.get("sample_id"),
        "sample_esi": {str(r["level"]): r["sample"] for r in sample.get("esi", [])},
        "metrics": run_metrics(results) if results else None,
        "_results": results,
    }

comparisons = []
for (a, ra), (b, rb) in itertools.combinations(runs.items(), 2):
    if ra["sample_id"] and ra["sample_id"] == rb["sample_id"] and ra["_results"] and rb["_results"]:
        for outcome in ("agreement", "under_triage"):
            try:
                comparisons.append({"run_a": a, "run_b": b,
                                    **compare_runs(ra["_results"], rb["_results"], outcome)})
            except Exception as exc:  # e.g. no overlapping cases yet
                comparisons.append({"run_a": a, "run_b": b, "outcome": outcome, "error": str(exc)})
for r in runs.values():
    del r["_results"]
json.dump({"runs": runs, "paired_comparisons": comparisons}, sys.stdout, indent=2, default=str)
print()
