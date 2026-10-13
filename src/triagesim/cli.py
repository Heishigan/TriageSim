"""TriageSim command line.

    triagesim ui                                   open the app (what the start files run)
    triagesim cohort check                         check the MIMIC files in data/
    triagesim cohort build --settings <yaml>       build a cohort into outputs/
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from .cohort.build import build_cohort, save_result
from .cohort.settings import CohortSettings
from . import paths
from .cohort.sources import DataLoadError, check_data, ensure_layout, layout_tree, load_tables


def _check(args) -> int:
    ensure_layout(args.data)
    results = check_data(args.data)
    for r in results:
        print(f"[{'OK' if r.ok else 'MISSING'}] {r.table.relative_path:<22} {r.message}")
    if not all(r.ok for r in results):
        print(f"\nPlace the files like this inside {Path(args.data).resolve()}:\n")
        print(layout_tree())
        return 1
    return 0


def _build(args) -> int:
    try:
        settings = CohortSettings.from_yaml(args.settings)
        result = build_cohort(load_tables(args.data), settings)
    except (OSError, ValueError, DataLoadError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for step in result.flow:
        print(f"{step.step:<40} {step.ed_stays:>9,} stays {step.patients:>9,} patients")
    for step in result.empty_steps()[:1]:
        print(f"Warning: no ED stays left after '{step}'.")
    try:
        run_dir = save_result(result, settings, args.output, args.data)
    except OSError as exc:
        print(f"Error: could not save results in {args.output}: {exc}", file=sys.stderr)
        return 1
    print(f"\nSaved to {run_dir}")
    return 0


def _build_cases(args) -> int:
    import pandas as pd
    from .cases.build import CaseSettings, build_cases, read_discharge_notes, save_cases
    run_dir = Path(args.cohort)
    if not (run_dir / "cohort.csv").is_file():
        print(f"Error: no cohort.csv in {run_dir}", file=sys.stderr)
        return 1
    purposes = ("cohort", "cases", "labels") if not args.no_labels else ("cohort", "cases")
    try:
        tables = load_tables(args.data, purposes, skip=("discharge",))
    except (OSError, DataLoadError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    cohort = pd.read_csv(run_dir / "cohort.csv")
    print("Reading discharge notes (large file, a few minutes)...", flush=True)
    notes = read_discharge_notes(Path(args.data) / "note/discharge.csv.gz", set(cohort["hadm_id"].dropna()),
                                 progress=lambda n: print(f"  {n:,} notes read", end="\r", flush=True))
    cases, flow = build_cases(cohort, tables, notes, CaseSettings())
    report = save_cases(run_dir, cases, flow, CaseSettings())
    print()
    for step in flow:
        print(f"{step['step']:<30} {step['cases']:>8,}")
    print(f"HPIs changed by redaction: {report['hpi_redacted']:,}")
    print(f"Saved {run_dir / 'cases.jsonl'}")
    return 0


def _pull_models(args) -> int:
    import os
    from .experiment.config import ExperimentConfig
    from .llm.base import ModelError
    from .llm.ollama import OllamaClient, ensure_model
    config = ExperimentConfig.from_yaml(args.experiment)
    client = OllamaClient(config.ollama_url)

    def show(p):
        total = p.get("total") or 0
        pct = f" {100 * p['completed'] / total:5.1f}%" if total else ""
        print(f"  {p['status'][:50]:<50}{pct}", end="\r", flush=True)

    try:
        for model in {m.name: m for m in config.models()}.values():
            print(f"{model.name}:")
            result = ensure_model(client, model, os.environ.get("HF_TOKEN"), paths.output_dir() / "models", show)
            print(f"  {result:<60}")
    except ModelError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    return 0


def _run(args) -> int:
    import signal
    import threading
    from .experiment.config import ExperimentConfig
    from .experiment.runner import create_run, execute, read_status
    if args.resume:
        run_dir = Path(args.resume)
    else:
        try:
            run_dir = create_run(ExperimentConfig.from_yaml(args.experiment))
        except (FileNotFoundError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())       # Slurm time limit: stop cleanly
    total = read_status(run_dir).get("total", 0)
    print(f"Run folder: {run_dir}\nCases: {total}", flush=True)

    def show(event):
        if event["type"] == "case_done":
            st = read_status(run_dir)
            print(f"[{st.get('done', 0) + 1}/{total}] {event['case_id']}: ESI {event['esi']} "
                  f"(reference {event['reference_esi']}), {event['questions']} questions", flush=True)
    try:
        status = execute(run_dir, stop=stop, on_event=show)
    except KeyboardInterrupt:
        stop.set()
        status = read_status(run_dir)
    print(f"State: {status.get('state')} ({status.get('done')}/{status.get('total')} cases)")
    if status.get("error"):
        print(status["error"], file=sys.stderr)
    return 0 if status.get("state") == "completed" else 1


DEFAULT_PORT = 8765


def _free_port(preferred: int | None = DEFAULT_PORT) -> int:
    """The preferred port if it is free (stable address between restarts), else any free one."""
    if preferred:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_ready(url: str, proc: subprocess.Popen, timeout: float = 90) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy
    deadline = time.time() + timeout
    while time.time() < deadline and proc.poll() is None:
        try:
            opener.open(f"{url}/api/ping", timeout=10)
            return True
        except OSError:
            time.sleep(0.5)
    return False


def _ui(args) -> int:
    """Start the local server (localhost only) and open the app in the browser."""
    import os
    if args.demo:   # invented data in demo/, never the real data/ and outputs/
        from .demo_data import make_demo_data
        demo = paths.REPO_ROOT / "demo"
        if not (demo / "data/hosp/patients.csv.gz").is_file():
            make_demo_data(demo / "data")
        os.environ["TRIAGESIM_DATA_DIR"] = str(demo / "data")
        os.environ["TRIAGESIM_OUTPUT_DIR"] = str(demo / "outputs")
        os.environ["TRIAGESIM_DEMO"] = "1"
        print("DEMO MODE: invented data, no real patients.", flush=True)
    port = args.port or _free_port()
    url = f"http://127.0.0.1:{port}"
    print("Starting TriageSim...", flush=True)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "triagesim.server.app:app",
                             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"])
    if not _wait_until_ready(url, proc):
        if proc.poll() is None:
            print(f"The app did not answer at {url} within 90 seconds.")
            proc.terminate()
        else:
            print(f"The app stopped with exit code {proc.returncode}. See the messages above.")
        print("To see the full error, run in this folder:\n"
              f"  uv run python -m uvicorn triagesim.server.app:app --port {port}")
        return 1
    print(f"\nTriageSim is running at {url}", flush=True)
    print("Close this window to stop it.\n", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="triagesim", description="TriageSim command line.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ui", help="open the app in the browser")
    p.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    p.add_argument("--port", type=int, default=None, help=f"port (default {DEFAULT_PORT}, or a free one if taken)")
    p.add_argument("--demo", action="store_true", help="use invented demo data (demo/) instead of data/")
    p.set_defaults(func=_ui)

    cohort = sub.add_parser("cohort", help="cohort builder").add_subparsers(dest="action", required=True)

    p = cohort.add_parser("check", help="check that the MIMIC files are in place")
    p.add_argument("--data", default=str(paths.data_dir()), help=argparse.SUPPRESS)
    p.set_defaults(func=_check)

    p = cohort.add_parser("build", help="build a cohort from a settings file")
    p.add_argument("--settings", required=True, help="YAML settings file")
    p.add_argument("--data", default=str(paths.data_dir()), help=argparse.SUPPRESS)
    p.add_argument("--output", default=str(paths.cohorts_dir()), help=argparse.SUPPRESS)
    p.set_defaults(func=_build)

    cases = sub.add_parser("cases", help="case builder").add_subparsers(dest="action", required=True)
    p = cases.add_parser("build", help="build case files for a saved cohort")
    p.add_argument("--cohort", required=True, help="folder of a saved cohort (in outputs/cohorts/)")
    p.add_argument("--data", default=str(paths.data_dir()), help=argparse.SUPPRESS)
    p.add_argument("--no-labels", action="store_true", help="skip labels (no hosp/diagnoses_icd file)")
    p.set_defaults(func=_build_cases)

    models = sub.add_parser("models", help="model downloads").add_subparsers(dest="action", required=True)
    p = models.add_parser("pull", help="download every model an experiment uses (HF_TOKEN for gated models)")
    p.add_argument("--experiment", required=True, help="experiment YAML file")
    p.set_defaults(func=_pull_models)

    p = sub.add_parser("run", help="run an experiment (or resume a stopped run)")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--experiment", help="experiment YAML file")
    group.add_argument("--resume", help="run folder to resume")
    p.set_defaults(func=_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
