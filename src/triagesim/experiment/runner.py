"""Run an experiment over many cases, with live progress, stop and resume.

A run lives in outputs/runs/<name>_<timestamp>/:
  experiment.yaml   the exact settings used
  plan.json         the cohort folder and the case ids, in order
  status.json       state, progress, current case (rewritten as the run goes)
  events.jsonl      every message and decision as it happens (for the live view)
  results.jsonl     one line per finished case
"""
from __future__ import annotations

import json
import random
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from .. import __version__, paths
from ..cases.build import load_cases
from ..llm.base import ChatModel, ModelError
from ..llm.demo import DemoModel, demo_embed
from ..llm.ollama import OllamaClient, OllamaModel
from .config import ExperimentConfig
from .engine import Stopped, run_case

STATES = ("created", "running", "stopping", "stopped", "completed", "failed")


def resolve_cohort(name: str, cohorts_dir: Path | None = None) -> Path:
    """A cohort folder by exact name, or the newest '<name>_<timestamp>' folder with case files."""
    root = cohorts_dir or paths.cohorts_dir()
    exact = root / name
    if (exact / "cases.jsonl").is_file():
        return exact
    candidates = sorted((p for p in root.glob(f"{name}_*") if (p / "cases.jsonl").is_file()),
                        key=lambda p: p.name, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No cohort '{name}' with case files in {root}. "
                                "Build the cohort and its cases first.")
    return candidates[0]


def sample_case_ids(cases: list[dict], config: ExperimentConfig) -> list[str]:
    ids = [c["case_id"] for c in cases if c["reference"]["esi"] is not None]
    if config.sampling.order == "random":
        random.Random(config.sampling.seed).shuffle(ids)
    return ids[: config.sampling.cases] if config.sampling.cases else ids


def create_run(config: ExperimentConfig, runs_dir: Path | None = None, cohorts_dir: Path | None = None) -> Path:
    """Prepare a run folder: settings, cohort and the planned cases."""
    cohort_dir = resolve_cohort(config.cohort, cohorts_dir)
    case_ids = sample_case_ids(load_cases(cohort_dir), config)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = runs_dir or paths.runs_dir()
    run_dir = root / f"{config.name}_{stamp}"
    n = 2
    while run_dir.exists():
        run_dir, n = root / f"{config.name}_{stamp}-{n}", n + 1
    run_dir.mkdir(parents=True)
    config.to_yaml(run_dir / "experiment.yaml")
    (run_dir / "plan.json").write_text(json.dumps({"cohort_dir": str(cohort_dir), "case_ids": case_ids}, indent=2))
    write_status(run_dir, state="created", total=len(case_ids), done=0, version=__version__,
                 created=datetime.now().isoformat(timespec="seconds"))
    return run_dir


def read_status(run_dir: Path) -> dict:
    try:
        return json.loads((Path(run_dir) / "status.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_status(run_dir: Path, **changes) -> dict:
    status = {**read_status(run_dir), **changes, "updated": datetime.now().isoformat(timespec="seconds")}
    tmp = Path(run_dir) / "status.json.tmp"
    tmp.write_text(json.dumps(status, indent=2))
    tmp.replace(Path(run_dir) / "status.json")
    return status


def read_results(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / "results.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_models(config: ExperimentConfig) -> tuple[dict[str, ChatModel], Callable | None]:
    """Model objects for every agent, plus an embedding function for a retrieval patient."""
    client = OllamaClient(config.ollama_url)
    models: dict[str, ChatModel] = {}
    for m in config.models():
        models[m.name] = DemoModel(m.name) if m.source == "demo" else OllamaModel(client, m.name)
    embed = None
    if config.patient and config.patient.mode == "retrieval":
        if config.patient.model.source == "demo":
            embed = demo_embed
        else:
            emb_model = config.patient.retrieval_embedding_model
            embed = lambda texts: client.embed(emb_model, texts)  # noqa: E731
    return models, embed


def execute(run_dir: Path, stop: threading.Event | None = None,
            models: dict[str, ChatModel] | None = None, embed: Callable | None = None,
            on_event: Callable[[dict], None] | None = None) -> dict:
    """Run (or resume) every planned case that has no result yet."""
    run_dir = Path(run_dir)
    stop = stop or threading.Event()
    config = ExperimentConfig.from_yaml(run_dir / "experiment.yaml")
    plan = json.loads((run_dir / "plan.json").read_text())
    cases = {c["case_id"]: c for c in load_cases(Path(plan["cohort_dir"]))}
    done_ids = {r["case_id"] for r in read_results(run_dir)}
    todo = [cid for cid in plan["case_ids"] if cid not in done_ids]
    if models is None:
        models, embed = build_models(config)
    write_status(run_dir, state="running", total=len(plan["case_ids"]), done=len(done_ids), error=None,
                 started=read_status(run_dir).get("started") or datetime.now().isoformat(timespec="seconds"))

    events = open(run_dir / "events.jsonl", "a", encoding="utf-8")

    def emit(event: dict) -> None:
        event = {"time": round(time.time(), 3), **event}
        events.write(json.dumps(event, ensure_ascii=False) + "\n")
        events.flush()
        if on_event:
            on_event(event)

    try:
        for case_id in todo:
            if stop.is_set():
                raise Stopped()
            write_status(run_dir, current_case=case_id)
            result = run_case(cases[case_id], config, models, emit=emit, should_stop=stop.is_set, embed=embed)
            with open(run_dir / "results.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
            done_ids.add(case_id)
            write_status(run_dir, done=len(done_ids))
        return write_status(run_dir, state="completed", current_case=None,
                            finished=datetime.now().isoformat(timespec="seconds"))
    except Stopped:
        emit({"type": "run_stopped"})
        return write_status(run_dir, state="stopped", current_case=None)
    except ModelError as exc:
        emit({"type": "run_failed", "error": str(exc)})
        return write_status(run_dir, state="failed", error=str(exc), current_case=None)
    except Exception as exc:  # keep the run folder consistent and say what happened
        emit({"type": "run_failed", "error": repr(exc)})
        return write_status(run_dir, state="failed", error=f"{exc!r}\n{traceback.format_exc(limit=5)}",
                            current_case=None)
    finally:
        events.close()


def list_runs(runs_dir: Path | None = None) -> list[Path]:
    root = runs_dir or paths.runs_dir()
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if (p / "status.json").is_file()),
                  key=lambda p: p.name, reverse=True)
