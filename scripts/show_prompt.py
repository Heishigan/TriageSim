"""Print the exact first prompt the nurse got for one case of a run, to check it by eye.

    uv run python scripts/show_prompt.py local_similar case-01276

The first argument is a run folder or just the experiment name (the newest run of that name).

Shows the system prompt (with the 40 similar cases, for that ablation), its length, the context
window the run asked for, and the largest prompt Ollama actually counted for this case. If the
counted prompt is far shorter than the estimate, the prompt was cut off.

Patient-level data: read it on this computer only; do not copy or share it.
"""
import json
import re
import sys
from pathlib import Path

from triagesim import paths
from triagesim.cases.build import load_cases
from triagesim.experiment import protocol as P
from triagesim.experiment.agents import choose_persona, system_message
from triagesim.experiment.config import ExperimentConfig
from triagesim.experiment.fields import case_values
from triagesim.experiment.runner import read_results


def main(run_dir: Path, case_id: str) -> int:
    config = ExperimentConfig.from_yaml(run_dir / "experiment.yaml")
    plan = json.loads((run_dir / "plan.json").read_text())
    cohort = re.split(r"[\\\\/]", plan["cohort_dir"].rstrip("/\\\\"))[-1]   # the run may come from another computer
    cases = {c["case_id"]: c for c in load_cases(paths.cohorts_dir() / cohort)}
    if case_id not in cases:
        print(f"No {case_id} in cohort {cohort}.")
        return 1
    case = cases[case_id]
    extra, shown = None, None
    if config.nurse.similar_cases:
        from triagesim.experiment.similar import SimilarCases, render_examples
        from triagesim.llm.ollama import OllamaClient
        from triagesim.experiment.runner import ollama_url
        pool = [cases[c] for c in json.loads((run_dir / "pool.json").read_text())["case_ids"]]
        sc = config.nurse.similar_cases
        client = OllamaClient(ollama_url(config))
        index = SimilarCases(pool, [case], lambda t: client.embed(sc.embedding_model, t, num_ctx=2048),
                             cache=run_dir / "pool_embeddings.json")
        examples = index.retrieve(case, sc.k, sc.candidates_per_example)
        extra, shown = {"similar_cases": render_examples(examples)}, [c["case_id"] for c in examples]
    persona = choose_persona(config.patient, case_id, config.sampling.seed) if config.patient else None
    values = case_values(case, persona=config.patient.personas.get(persona, "") if config.patient else "", extra=extra)
    instructions = {"chart_review": P.DECISION_INSTRUCTIONS, "multiple_choice": P.MULTIPLE_CHOICE_INSTRUCTIONS,
                    "interview": P.NURSE_TURN_INSTRUCTIONS}[config.nurse.mode]
    prompt = system_message(config.nurse, values, instructions).content
    print("=" * 100)
    print(prompt)
    print("=" * 100)
    print(f"Run {run_dir.name} · {case_id} · nurse {config.nurse.model.name} · mode {config.nurse.mode}")
    print(f"Prompt: {len(prompt):,} characters, roughly {len(prompt) // 4:,} tokens")
    print(f"Context window asked for: {config.nurse.model.num_ctx or 'Ollama default (not set)'}")
    result = next((r for r in read_results(run_dir) if r["case_id"] == case_id), None)
    if result is None:
        print("No result for this case yet.")
    else:
        counted = (result.get("max_prompt_tokens") or {}).get("nurse")
        print(f"Largest nurse prompt Ollama counted: {counted if counted else 'not recorded (older run)'}"
              f"{' · CONTEXT FULL: prompt probably cut off' if result.get('context_full') else ''}")
        if shown is not None and result.get("similar_case_ids") not in (None, shown):
            print("WARNING: these examples differ from the ones the run recorded.")
        elif shown is not None:
            print("Similar cases match the ones the run recorded.")
    return 0


def find_run_dir(arg: str) -> Path | None:
    path = Path(arg)
    if (path / "experiment.yaml").is_file():
        return path
    from triagesim.experiment.runner import find_run
    return find_run(arg.strip().rstrip("/\\"))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # Windows consoles default to a narrower code page
    except (AttributeError, ValueError):
        pass
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    run = find_run_dir(sys.argv[1])
    if run is None:
        print(f"No run folder or experiment named '{sys.argv[1]}' in {paths.runs_dir()}.")
        sys.exit(1)
    sys.exit(main(run, sys.argv[2].strip()))
