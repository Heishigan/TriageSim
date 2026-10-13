"""TriageSim local API (FastAPI). Started by `triagesim ui`; listens on localhost only.

Patient-level data is only ever served to the local browser; nothing is sent elsewhere
except model downloads (Ollama library / Hugging Face) that the user starts.
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from .. import __version__, paths, settings_store
from ..cases.build import CaseSettings, build_cases, load_cases, read_discharge_notes, save_cases
from ..cohort import review as cohort_review
from ..cohort.build import build_cohort, save_result
from ..cohort.settings import CohortSettings
from ..cohort.sources import PURPOSES, DataLoadError, check_data, layout_tree, load_tables
from ..experiment.config import ExperimentConfig
from ..experiment.fields import FIELDS
from ..experiment.runner import create_run, execute, list_runs, read_results, read_status
from ..llm.base import ModelError
from ..llm.demo import DemoModel
from ..llm.ollama import OllamaClient, OllamaModel, ensure_model
from ..results.metrics import compare_runs, run_metrics
from ..results.summary import summarize_metrics
from .jobs import JobManager

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
app = FastAPI(title="TriageSim", version=__version__)
jobs = JobManager()
_tables_cache: dict[tuple, dict] = {}
_tables_lock = threading.Lock()


# ---- helpers ------------------------------------------------------------------------
def _ollama(quick: bool = False) -> OllamaClient:
    """Ollama client. ``quick`` = short timeout, for status checks that must not hang."""
    return OllamaClient(settings_store.load()["ollama_url"], timeout=3.0 if quick else 600.0)


def _cached_tables(purposes: tuple[str, ...], skip: tuple[str, ...] = ()) -> dict[str, pd.DataFrame]:
    """MIMIC tables, loaded once per set of file versions."""
    checks = check_data(paths.data_dir(), purposes)
    if not all(c.ok for c in checks):
        missing = "; ".join(f"{c.table.relative_path}: {c.message}" for c in checks if not c.ok)
        raise HTTPException(400, f"Data files not ready: {missing}")
    key = (purposes, skip) + tuple((str(c.path), c.path.stat().st_mtime) for c in checks)
    with _tables_lock:
        if key not in _tables_cache:
            _tables_cache.clear()
            _tables_cache[key] = load_tables(paths.data_dir(), purposes, skip=skip)
        return _tables_cache[key]


def _cohort_dir(name: str) -> Path:
    path = paths.cohorts_dir() / name
    if not (path / "cohort.csv").is_file() or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(404, f"No cohort '{name}'")
    return path


def _run_dir(name: str) -> Path:
    path = paths.runs_dir() / name
    if not (path / "status.json").is_file() or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(404, f"No run '{name}'")
    return path


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _validation_errors(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"] for e in exc.errors()]


# ---- system -------------------------------------------------------------------------
@app.get("/api/ping")
def ping() -> dict:
    """Answers immediately; used by the launcher to know the app is up."""
    return {"ok": True}


@app.get("/api/health")
def health() -> dict:
    try:
        ollama = {"reachable": True, "version": _ollama(quick=True).version()}
    except ModelError as exc:
        ollama = {"reachable": False, "error": str(exc)}
    return {"version": __version__, "ollama": ollama, "settings": settings_store.public(settings_store.load())}


class SettingsIn(BaseModel):
    ollama_url: str | None = None
    hf_token: str | None = None


@app.put("/api/settings")
def update_settings(body: SettingsIn) -> dict:
    return settings_store.public(settings_store.save(body.model_dump()))


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return [j.public() for j in jobs.all()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "No such job")
    return job.public()


# ---- data ---------------------------------------------------------------------------
@app.get("/api/data")
def data_check() -> dict:
    from ..cohort.sources import ensure_layout
    ensure_layout(paths.data_dir())
    groups = []
    for purpose, label in PURPOSES.items():
        checks = check_data(paths.data_dir(), (purpose,))
        groups.append({"purpose": purpose, "label": label, "ready": all(c.ok for c in checks),
                       "files": [{"path": f"data/{c.table.relative_path}", "ok": c.ok, "message": c.message,
                                  "source": c.table.source, "url": c.table.url} for c in checks]})
    return {"data_dir": str(paths.data_dir()), "tree": layout_tree("TriageSim/data"), "groups": groups}


@app.post("/api/data/open-folder")
def open_data_folder() -> dict:
    import os
    import subprocess
    import sys
    folder = paths.data_dir()
    if sys.platform.startswith("win"):
        os.startfile(folder)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
    return {"opened": str(folder)}


# ---- cohorts ------------------------------------------------------------------------
@app.get("/api/cohort-presets")
def cohort_presets() -> list[dict]:
    from dataclasses import asdict
    out = []
    for p in sorted(paths.COHORT_PRESETS.glob("*.yaml")):
        try:
            out.append({"name": p.stem, "settings": asdict(CohortSettings.from_yaml(p))})
        except ValueError:
            continue
    return out


@app.post("/api/cohorts")
def create_cohort(body: dict) -> dict:
    try:
        settings = CohortSettings(**body)
        settings.validate()
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc))
    try:
        result = build_cohort(_cached_tables(("cohort",)), settings)
        run_dir = save_result(result, settings, paths.cohorts_dir(), paths.data_dir())
    except DataLoadError as exc:
        raise HTTPException(400, str(exc))
    return {"name": run_dir.name, "filters": settings.describe(), **result.summary()}


@app.get("/api/cohorts")
def list_cohorts() -> list[dict]:
    root = paths.cohorts_dir()
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.iterdir(), key=lambda p: p.name, reverse=True):
        report = _read_json(p / "report.json")
        if not report:
            continue
        out.append({"name": p.name, "created": report.get("created"),
                    "patients": report["flow"][-1]["patients"] if report.get("flow") else None,
                    "cases": (_read_json(p / "cases_report.json") or {}).get("cases")})
    return out


@app.get("/api/cohorts/{name}")
def get_cohort(name: str) -> dict:
    d = _cohort_dir(name)
    settings = CohortSettings.from_yaml(d / "settings.yaml")
    return {"name": name, "filters": settings.describe(), "report": _read_json(d / "report.json"),
            "cases_report": _read_json(d / "cases_report.json"),
            "case_job": next((j.public() for j in jobs.running("cases") if j.label == name), None)}


@app.post("/api/cohorts/{name}/cases")
def start_case_build(name: str) -> dict:
    d = _cohort_dir(name)
    if jobs.running("cases"):
        raise HTTPException(409, "A case build is already running.")
    labels = all(c.ok for c in check_data(paths.data_dir(), ("labels",)))
    purposes = ("cohort", "cases", "labels") if labels else ("cohort", "cases")
    if not all(c.ok for c in check_data(paths.data_dir(), ("cases",))):
        raise HTTPException(400, "The case builder files are not all in place (see Data).")

    def work(job):
        job.progress = {"status": "loading tables"}
        tables = _cached_tables(purposes, skip=("discharge",))
        cohort = pd.read_csv(d / "cohort.csv")
        job.progress = {"status": "reading discharge notes", "notes_read": 0}
        notes = read_discharge_notes(paths.data_dir() / "note/discharge.csv.gz", set(cohort["hadm_id"].dropna()),
                                     progress=lambda n: job.progress.update(notes_read=n))
        job.progress = {"status": "building cases"}
        cases, flow = build_cases(cohort, tables, notes, CaseSettings())
        return save_cases(d, cases, flow, CaseSettings())

    return jobs.start("cases", name, work).public()


@app.get("/api/cohorts/{name}/cases")
def list_cases(name: str, limit: int = 20, offset: int = 0) -> dict:
    cases = load_cases(_cohort_dir(name))
    return {"total": len(cases), "cases": cases[offset: offset + limit]}


@app.get("/api/cohorts/{name}/review")
def review_sample(name: str, group: str = "included", n: int = 10, seed: int = 1) -> dict:
    d = _cohort_dir(name)
    tables = _cached_tables(("cohort",))
    run = cohort_review.rebuild(tables, d)
    if group == "included":
        pool = run.result.cohort["stay_id"]
    else:
        pool = run.result.excluded.loc[run.result.excluded["excluded_at"] == group, "stay_id"]
    ids = cohort_review.sample_cases(pool, n, seed)
    verdicts = cohort_review.load_review(d)
    verdicts = {int(r.stay_id): {"verdict": r.verdict, "note": "" if pd.isna(r.note) else r.note}
                for r in verdicts.itertuples()} if len(verdicts) else {}
    cases = []
    for sid in ids:
        det = cohort_review.case_details(tables, run, sid)
        cases.append({"stay_id": int(sid), "facts": {k: str(v) for k, v in det["facts"].items()},
                      "diagnoses": json.loads(det["diagnoses"].to_json(orient="records")),
                      "visits": json.loads(det["visits"].to_json(orient="records", date_format="iso")),
                      "verdict": verdicts.get(int(sid))})
    groups = ["included"] + [s.step for s in run.result.flow[1:]]
    return {"reproduced": run.reproduced, "groups": groups, "pool": int(len(pool)), "cases": cases}


class VerdictIn(BaseModel):
    stay_id: int
    group: str
    verdict: str
    note: str = ""


@app.post("/api/cohorts/{name}/review")
def save_verdict(name: str, body: VerdictIn) -> dict:
    try:
        cohort_review.save_verdict(_cohort_dir(name), body.stay_id, body.group, body.verdict, body.note)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"saved": True}


# ---- models -------------------------------------------------------------------------
@app.get("/api/models")
def installed_models() -> dict:
    try:
        return {"reachable": True, "models": _ollama(quick=True).list_models(),
                "downloads": [j.public() for j in jobs.all() if j.kind == "model"]}
    except ModelError as exc:
        return {"reachable": False, "error": str(exc), "models": [],
                "downloads": [j.public() for j in jobs.all() if j.kind == "model"]}


class ModelIn(BaseModel):
    name: str
    source: str = "ollama"
    hf_repo: str | None = None
    hf_file: str | None = None


@app.post("/api/models/pull")
def pull_model(body: ModelIn) -> dict:
    from ..experiment.config import ModelSettings
    try:
        model = ModelSettings(**body.model_dump())
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(_validation_errors(exc)))
    settings = settings_store.load()

    def work(job):
        def progress(p):
            job.progress = p
        return {"result": ensure_model(_ollama(), model, settings["hf_token"] or None,
                                       paths.output_dir() / "models", progress)}
    return jobs.start("model", body.name, work).public()


class TestIn(BaseModel):
    name: str
    source: str = "ollama"
    message: str = "In one sentence: what is the Emergency Severity Index?"


@app.post("/api/models/test")
def test_model(body: TestIn) -> dict:
    from ..llm.base import Message
    model = DemoModel(body.name) if body.source == "demo" else OllamaModel(_ollama(), body.name)
    try:
        r = model.chat([Message("user", body.message)], temperature=0.2)
    except ModelError as exc:
        raise HTTPException(502, str(exc))
    return {"reply": r.content, "seconds": round(r.seconds, 2), "tokens": r.prompt_tokens + r.completion_tokens}


# ---- experiments ----------------------------------------------------------------------
@app.get("/api/experiment-presets")
def experiment_presets() -> list[dict]:
    out = []
    for p in sorted(paths.EXPERIMENT_PRESETS.glob("*.yaml")):
        try:   # with every default filled in, so the editor shows exactly what will run
            out.append({"name": p.stem, "config": ExperimentConfig.from_yaml(p).model_dump(mode="json")})
        except ValidationError:
            continue
    return out


@app.get("/api/fields")
def fields() -> dict:
    return {k: {"source": s, "description": d} for k, (s, d) in FIELDS.items()}


@app.post("/api/experiments/validate")
def validate_experiment(body: dict) -> dict:
    try:
        ExperimentConfig.model_validate(body)
    except ValidationError as exc:
        return {"valid": False, "errors": _validation_errors(exc)}
    return {"valid": True, "errors": []}


@app.post("/api/experiments/yaml")
def experiment_yaml(body: dict):
    """The experiment as a YAML file, e.g. to run it on a cluster with 'triagesim run'."""
    from fastapi.responses import PlainTextResponse
    try:
        config = ExperimentConfig.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(_validation_errors(exc)))
    text = yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=100)
    return PlainTextResponse(text, headers={"Content-Disposition": f'attachment; filename="{config.name}.yaml"'})


# ---- runs ---------------------------------------------------------------------------
def _start_run(run_dir: Path) -> None:
    def work(job):
        return execute(run_dir, stop=job.stop)
    jobs.start("run", run_dir.name, work, job_id=run_dir.name)


@app.post("/api/runs")
def start_run(body: dict) -> dict:
    try:
        config = ExperimentConfig.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(_validation_errors(exc)))
    try:
        run_dir = create_run(config)
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc))
    _start_run(run_dir)
    return {"name": run_dir.name}


@app.get("/api/runs")
def runs() -> list[dict]:
    out = []
    for d in list_runs():
        st = read_status(d)
        cfg = yaml.safe_load((d / "experiment.yaml").read_text(encoding="utf-8")) or {}
        out.append({"name": d.name, "experiment": cfg.get("name"), "mode": cfg.get("nurse", {}).get("mode"),
                    **{k: st.get(k) for k in ("state", "done", "total", "created", "updated")}})
    return out


@app.get("/api/runs/{name}")
def run_detail(name: str) -> dict:
    d = _run_dir(name)
    status = read_status(d)
    job = jobs.get(name)
    if status.get("state") in ("running", "stopping") and not (job and job.state == "running"):
        status["state"] = "interrupted"     # the app was closed while it ran; it can be resumed
    return {"name": name, "status": status,
            "config": yaml.safe_load((d / "experiment.yaml").read_text(encoding="utf-8")),
            "plan": _read_json(d / "plan.json")}


@app.post("/api/runs/{name}/stop")
def stop_run(name: str) -> dict:
    _run_dir(name)
    job = jobs.get(name)
    if job and job.state == "running":
        job.stop.set()
        return {"stopping": True}
    return {"stopping": False}


@app.post("/api/runs/{name}/resume")
def resume_run(name: str) -> dict:
    d = _run_dir(name)
    job = jobs.get(name)
    if job and job.state == "running":
        raise HTTPException(409, "This run is already running.")
    _start_run(d)
    return {"resumed": True}


@app.get("/api/runs/{name}/events")
async def run_events(name: str, after: int = 0):
    """Server-sent events: every event line from ``after`` on, then new ones as they come."""
    d = _run_dir(name)

    async def stream():
        sent = after
        idle = 0
        while True:
            path = d / "events.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
            for line in lines[sent:]:
                sent += 1
                yield f"id: {sent}\ndata: {line}\n\n"
            state = read_status(d).get("state")
            job = jobs.get(name)
            if state not in ("running", "created", "stopping") or (job and job.state != "running" and idle > 2):
                yield f"event: end\ndata: {json.dumps({'state': state})}\n\n"
                return
            idle = idle + 1 if len(lines) == sent else 0
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _row(r: dict) -> dict:
    return {k: r.get(k) for k in ("case_id", "stay_id", "persona", "reference_esi", "esi_initial", "esi_final",
                                  "head_injury", "decided", "forced", "questions", "seconds", "format_failures")} | {
        "scores": (r.get("evaluation") or {}).get("scores")}


@app.get("/api/runs/{name}/results")
def run_results(name: str) -> dict:
    results = read_results(_run_dir(name))
    return {"metrics": run_metrics(results), "cases": [_row(r) for r in results]}


@app.get("/api/runs/{name}/cases/{case_id}")
def run_case_detail(name: str, case_id: str) -> dict:
    for r in read_results(_run_dir(name)):
        if r["case_id"] == case_id:
            return r
    raise HTTPException(404, "No result for this case yet")


@app.post("/api/runs/{name}/summary")
def run_summary(name: str) -> dict:
    d = _run_dir(name)
    config = ExperimentConfig.from_yaml(d / "experiment.yaml")
    m = config.evaluator.model if config.evaluator else config.nurse.model
    model = DemoModel(m.name) if m.source == "demo" else OllamaModel(_ollama(), m.name)
    try:
        text = summarize_metrics(model, config.name, run_metrics(read_results(d)))
    except ModelError as exc:
        raise HTTPException(502, str(exc))
    (d / "summary.txt").write_text(text, encoding="utf-8")
    return {"summary": text, "model": m.name}


@app.get("/api/compare")
def compare(a: str, b: str, outcome: str = "under_triage") -> dict:
    if outcome not in ("under_triage", "agreement", "head_injury_under_triage"):
        raise HTTPException(422, "Unknown outcome")
    return compare_runs(read_results(_run_dir(a)), read_results(_run_dir(b)), outcome)


# ---- front end ----------------------------------------------------------------------
if (WEB_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api"):
        raise HTTPException(404, "Unknown API address")
    index = WEB_DIR / "index.html"
    if not index.is_file():
        return {"message": "The front end is not built. Run 'npm run build' in frontend/."}
    return FileResponse(index)
