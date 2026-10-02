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


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("localhost", 0))
        return sock.getsockname()[1]


def _wait_until_ready(url: str, proc: subprocess.Popen, timeout: float = 60) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy
    deadline = time.time() + timeout
    while time.time() < deadline and proc.poll() is None:
        try:
            opener.open(f"{url}/_stcore/health", timeout=1)
            return True
        except OSError:
            time.sleep(0.5)
    return False


def _ui(args) -> int:
    app = Path(__file__).parent / "ui" / "app.py"
    port = _free_port()
    url = f"http://localhost:{port}"
    proc = subprocess.Popen([
        sys.executable, "-m", "streamlit", "run", str(app),
        "--server.address", "localhost",          # reachable from this computer only
        "--server.port", str(port),
        "--server.headless", "true",              # no first-run prompt; we open the browser
        "--browser.gatherUsageStats", "false",    # no telemetry
        "--server.fileWatcherType", "none",
    ])
    if not _wait_until_ready(url, proc):
        print("The app did not start. See the messages above.")
        proc.terminate()
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
    p.set_defaults(func=_ui)

    cohort = sub.add_parser("cohort", help="cohort builder").add_subparsers(dest="action", required=True)

    p = cohort.add_parser("check", help="check that the MIMIC files are in place")
    p.add_argument("--data", default=str(paths.data_dir()), help=argparse.SUPPRESS)
    p.set_defaults(func=_check)

    p = cohort.add_parser("build", help="build a cohort from a settings file")
    p.add_argument("--settings", required=True, help="YAML settings file")
    p.add_argument("--data", default=str(paths.data_dir()), help=argparse.SUPPRESS)
    p.add_argument("--output", default=str(paths.output_dir()), help=argparse.SUPPRESS)
    p.set_defaults(func=_build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
