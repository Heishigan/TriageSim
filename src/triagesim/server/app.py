"""TriageSim local API (FastAPI). Started by `triagesim ui`; listens on localhost only.

Patient-level data is only ever served to the local browser; nothing is sent elsewhere
except model downloads (Ollama library / Hugging Face) that the user starts.
"""
from __future__ import annotations

import asyncio
import json
import shutil
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
from ..logs import Throttle, configure as configure_logging, log
from ..cases.build import CaseSettings, build_cases, load_cases, read_discharge_notes, save_cases
from ..cohort import review as cohort_review
from ..cohort.build import build_cohort, save_result
from ..cohort.settings import CohortSettings
from ..cohort.sources import PURPOSES, DataLoadError, check_data, layout_tree, load_tables
from ..experiment.config import ExperimentConfig
from ..experiment.fields import FIELDS
from ..experiment.runner import create_run, execute, is_alive, list_runs, read_results, read_status
from ..llm.base import ModelError
from ..llm.demo import DemoModel
from ..llm.ollama import (INSTALL_HELP, OllamaClient, OllamaModel, detect_gpus, ensure_model, find_ollama,
                          install_ollama_windows, start_ollama)
from ..results.metrics import compare_runs, run_metrics
from ..results.summary import summarize_metrics
from .jobs import JobManager

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
configure_logging()


def _startup_banner() -> None:
    import os
    log.info("TriageSim %s%s", __version__, "  [DEMO MODE: invented data]" if os.environ.get("TRIAGESIM_DEMO") == "1" else "")
    log.info("Data folder:    %s", paths.data_dir())
    log.info("Output folder:  %s", paths.output_dir())
    for purpose, label in PURPOSES.items():
        missing = [c.table.relative_path for c in check_data(paths.data_dir(), (purpose,)) if not c.ok]
        log.info("%-16s %s", label + ":", "ready" if not missing else "missing " + ", ".join(missing))
    try:
        log.info("Ollama:         %s at %s", _ollama(quick=True).version(), settings_store.load()["ollama_url"])
    except ModelError:
        log.warning("Ollama:         not reachable (%s)", "installed but stopped" if find_ollama() else "not installed")


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def _lifespan(_app):
    _startup_banner()
    yield


app = FastAPI(title="TriageSim", version=__version__, lifespan=_lifespan)

TOKEN_COOKIE = "triagesim_token"


@app.middleware("http")
async def _require_token(request, call_next):
    """When TRIAGESIM_ACCESS_TOKEN is set (app reachable beyond this computer, e.g. on a
    cluster node), every request needs it: once as ?token=... (stored as a cookie), then the
    cookie. /api/ping stays open so the launcher can see the app is up; it returns no data."""
    import hmac
    import os
    from fastapi.responses import PlainTextResponse, RedirectResponse
    token = os.environ.get("TRIAGESIM_ACCESS_TOKEN", "")
    if not token or request.url.path == "/api/ping":
        return await call_next(request)
    given = request.query_params.get("token")
    if given is not None and hmac.compare_digest(given.encode(), token.encode()):
        response = RedirectResponse(request.url.path, status_code=303)
        response.set_cookie(TOKEN_COOKIE, token, httponly=True, samesite="strict")
        return response
    if hmac.compare_digest(request.cookies.get(TOKEN_COOKIE, "").encode(), token.encode()):
        return await call_next(request)
    return PlainTextResponse("TriageSim: open the full address with ?token=... "
                             "(see the job log for where to find it).", status_code=401)
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
    ollama["installed"] = ollama["reachable"] or find_ollama() is not None
    import os
    import sys
    ollama["platform"] = "windows" if sys.platform.startswith("win") else sys.platform
    ollama["install_command"] = INSTALL_HELP.get(sys.platform)
    ollama["installing"] = bool(jobs.running("ollama-install"))
    return {"version": __version__, "ollama": ollama, "demo": os.environ.get("TRIAGESIM_DEMO") == "1",
            "settings": settings_store.public(settings_store.load())}


@app.post("/api/ollama/install")
def ollama_install() -> dict:
    """One-click install on Windows; elsewhere the command to run is returned in /api/health."""
    import sys
    if not sys.platform.startswith("win"):
        raise HTTPException(400, f"Install Ollama with: {INSTALL_HELP.get(sys.platform, 'see https://ollama.com/download')}")
    if jobs.running("ollama-install"):
        raise HTTPException(409, "Ollama is already being installed.")

    def work(job):
        throttle = Throttle("Ollama install", step=20)

        def progress(p):
            job.progress = p
            throttle(p)
        install_ollama_windows(progress)
        log.info("Ollama installed; waiting for it to start")
        import time as _time
        for _ in range(30):
            try:
                return {"version": _ollama(quick=True).version()}
            except ModelError:
                _time.sleep(1)
        exe = find_ollama()
        if exe:
            start_ollama(exe)
        return {"version": None}
    log.info("Installing Ollama (downloading the official installer from ollama.com)")
    return jobs.start("ollama-install", "Ollama", work).public()


@app.post("/api/ollama/start")
def ollama_start() -> dict:
    """Start Ollama if it is installed but not running."""
    import time as _time
    try:
        return {"started": False, "already_running": True, "version": _ollama(quick=True).version()}
    except ModelError:
        pass
    exe = find_ollama()
    if not exe:
        raise HTTPException(404, "Ollama is not installed. Download it from https://ollama.com/download")
    start_ollama(exe)
    for _ in range(20):
        _time.sleep(0.5)
        try:
            return {"started": True, "version": _ollama(quick=True).version()}
        except ModelError:
            continue
    raise HTTPException(504, "Ollama was started but is not answering yet. Try again in a moment.")


class ClientError(BaseModel):
    message: str
    where: str = ""
    stack: str = ""


@app.post("/api/client-error")
def client_error(body: ClientError) -> dict:
    """Errors from the browser, shown in the terminal so they can be read and reported."""
    log.error("Browser error on %s: %s\n%s", body.where or "?", body.message[:500], body.stack[:2000])
    return {"logged": True}


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
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", str(folder)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except OSError as exc:
        raise HTTPException(500, f"Could not open the folder ({exc}). Open it yourself: {folder}")
    _ = os  # kept for platforms that need it
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
    log.info("Building cohort '%s': %s", settings.name, "; ".join(settings.describe()) or "no filters")
    try:
        result = build_cohort(_cached_tables(("cohort",)), settings)
        run_dir = save_result(result, settings, paths.cohorts_dir(), paths.data_dir())
    except DataLoadError as exc:
        log.error("Cohort build failed: %s", exc)
        raise HTTPException(400, str(exc))
    for step in result.flow:
        log.info("  %-40s %9s stays %9s patients", step.step, f"{step.ed_stays:,}", f"{step.patients:,}")
    log.info("Cohort saved: %s", run_dir.name)
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


def _runs_using(cohort: str) -> list[dict]:
    out = []
    for d in list_runs():
        if _run_cohort(d) == cohort:
            out.append({"name": d.name, "active": _run_is_active(d.name, read_status(d))})
    return out


@app.get("/api/cohorts/{name}/runs")
def cohort_runs(name: str) -> list[dict]:
    """Runs made from this cohort (shown before deleting it)."""
    _cohort_dir(name)
    return _runs_using(name)


@app.delete("/api/cohorts/{name}")
def delete_cohort(name: str) -> dict:
    """Delete a cohort folder with its case files. Runs made from it keep their results but can no
    longer be resumed; a cohort in use by a running run or a case build cannot be deleted."""
    d = _cohort_dir(name)
    if any(j.label == name for j in jobs.running("cases")):
        raise HTTPException(409, "Case files are being built for this cohort; wait until that finishes.")
    active = [r["name"] for r in _runs_using(name) if r["active"]]
    if active:
        raise HTTPException(409, "These runs are still using this cohort: " + ", ".join(active) + ". Stop them first.")
    _remove_folder(d, f"cohort {name}")
    log.info("Deleted cohort %s", name)
    return {"deleted": name}


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
    missing = [c for c in check_data(paths.data_dir(), ("cases",)) if not c.ok]
    if missing:
        raise HTTPException(400, "The case builder needs: " + "; ".join(
            f"data/{c.table.relative_path} ({c.message})" for c in missing))

    def work(job):
        log.info("Building case files for %s", name)
        job.progress = {"status": "loading tables"}
        tables = _cached_tables(purposes, skip=("discharge",))
        cohort = pd.read_csv(d / "cohort.csv")
        job.progress = {"status": "reading discharge notes", "notes_read": 0}
        log.info("Reading discharge notes (a few minutes)")

        def notes_progress(n):
            job.progress.update(notes_read=n)
            if n % 100_000 < 20_000:
                log.info("  %s notes read", f"{n:,}")
        notes = read_discharge_notes(paths.data_dir() / "note/discharge.csv.gz", set(cohort["hadm_id"].dropna()),
                                     progress=notes_progress)
        job.progress = {"status": "building cases"}
        cases, flow = build_cases(cohort, tables, notes, CaseSettings())
        report = save_cases(d, cases, flow, CaseSettings())
        for step in flow:
            log.info("  %-30s %9s", step["step"], f"{step['cases']:,}")
        log.info("Case files saved: %s cases, %s HPIs changed by redaction", f"{report['cases']:,}",
                 f"{report['hpi_redacted']:,}")
        return report

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


@app.get("/api/model-catalog")
def model_catalog() -> dict:
    """Curated local models by hardware tier, marked installed / fits this machine."""
    data = yaml.safe_load((paths.CONFIG_DIR / "models.yaml").read_text(encoding="utf-8"))
    try:
        installed = {m["name"] for m in _ollama(quick=True).list_models()}
    except ModelError:
        installed = set()
    gpus = detect_gpus()
    vram = max((g["memory_gb"] for g in gpus), default=0)
    models = []
    for m in data["models"]:
        full = m["name"] if ":" in m["name"] else f"{m['name']}:latest"
        models.append({**m, "tags": m.get("tags", []), "note": m.get("note", ""),
                       "installed": full in installed or m["name"] in installed,
                       "fits_gpu": bool(vram) and m["memory_gb"] <= vram})
    return {"tiers": data["tiers"], "models": models, "gpus": gpus, "gpu_memory_gb": vram}


@app.post("/api/models/pull")
def pull_model(body: ModelIn) -> dict:
    from ..experiment.config import ModelSettings
    try:
        model = ModelSettings(**body.model_dump())
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(_validation_errors(exc)))
    settings = settings_store.load()

    def work(job):
        throttle = Throttle(f"Model {body.name}")

        def progress(p):
            job.progress = p
            throttle(p)
        result = ensure_model(_ollama(), model, settings["hf_token"] or None, paths.output_dir() / "models", progress)
        log.info("Model %s: %s", body.name, result)
        return {"result": result}
    log.info("Model %s: download requested", body.name)
    return jobs.start("model", body.name, work).public()


@app.delete("/api/models/{name:path}")
def delete_model(name: str) -> dict:
    """Delete an installed model, unless a running experiment is using it."""
    for job in jobs.running("run"):
        cfg = ExperimentConfig.from_yaml(paths.runs_dir() / job.label / "experiment.yaml")
        if name in {m.name for m in cfg.models()}:
            raise HTTPException(409, f"{name} is used by the running experiment {job.label}. Stop it first.")
    try:
        _ollama().delete(name)
    except ModelError as exc:
        raise HTTPException(502, str(exc))
    log.info("Model %s: deleted", name)
    return {"deleted": name}


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
    def on_event(event):
        if event["type"] == "case_done":
            st = read_status(run_dir)
            log.info("Run %s [%s/%s] %s: agent ESI %s, nurse ESI %s, %s questions", run_dir.name,
                     st.get("done", 0) + 1, st.get("total"), event["case_id"], event.get("esi"),
                     event.get("reference_esi"), event.get("questions"))
        elif event["type"] == "run_failed":
            log.error("Run %s failed: %s", run_dir.name, event.get("error"))

    def work(job):
        status = execute(run_dir, stop=job.stop, on_event=on_event)
        log.info("Run %s: %s (%s/%s cases)", run_dir.name, status.get("state"), status.get("done"), status.get("total"))
        return status
    log.info("Run %s: starting", run_dir.name)
    jobs.start("run", run_dir.name, work, job_id=run_dir.name)


@app.post("/api/runs")
def start_run(body: dict) -> dict:
    try:
        config = ExperimentConfig.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(_validation_errors(exc)))
    needed = sorted({m.name for m in config.models() if m.source == "ollama"})
    if config.patient and config.patient.mode == "retrieval" and config.patient.model.source == "ollama":
        needed.append(config.patient.retrieval_embedding_model)
    if needed:
        try:
            installed = {m["name"] for m in _ollama(quick=True).list_models()}
        except ModelError as exc:
            raise HTTPException(400, f"{exc} Start Ollama (see Models) or use the Demo model.")
        missing = [n for n in needed if n not in installed and f"{n}:latest" not in installed]
        if missing:
            raise HTTPException(400, f"Not downloaded yet: {', '.join(missing)}. Download under Models, "
                                     "or choose an installed model.")
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
        state = st.get("state")
        if state in ("running", "stopping") and not jobs.get(d.name) and not is_alive(st):
            state = "interrupted"
        out.append({"name": d.name, "experiment": cfg.get("name"), "mode": cfg.get("nurse", {}).get("mode"),
                    "type": _run_type(cfg), "models": _run_models(cfg), "cohort": _run_cohort(d),
                    **{k: st.get(k) for k in ("done", "total", "created", "updated")}, "state": state})
    return out


def _run_type(cfg: dict) -> str:
    """'Interview · random personas', 'Chart review', ... for the runs list."""
    nurse, patient = cfg.get("nurse") or {}, cfg.get("patient") or {}
    mode = nurse.get("mode", "interview")
    if mode != "interview":
        return {"chart_review": "Chart review", "multiple_choice": "Multiple choice"}.get(mode, mode)
    label = "Interview"
    if patient.get("mode") == "retrieval":
        label += " · retrieval patient"
    elif patient.get("persona") == "random":
        label += " · random personas"
    elif patient.get("persona") not in (None, "neutral"):
        label += f" · {patient['persona']} persona"
    return label


def _run_models(cfg: dict) -> dict:
    """The model behind each agent that takes part (None when the agent is not used)."""
    nurse = cfg.get("nurse") or {}
    interview = nurse.get("mode", "interview") == "interview"
    evaluator = cfg.get("evaluator") or {}
    name = lambda agent: ((agent or {}).get("model") or {}).get("name")  # noqa: E731
    return {"nurse": name(nurse),
            "patient": name(cfg.get("patient")) if interview else None,
            "evaluator": name(evaluator) if evaluator.get("enabled") else None}


def _run_cohort(run_dir: Path) -> str | None:
    plan = _read_json(run_dir / "plan.json") or {}
    return Path(plan["cohort_dir"]).name if plan.get("cohort_dir") else None


def _run_is_active(name: str, status: dict) -> bool:
    job = jobs.get(name)
    return bool(job and job.state == "running") or (status.get("state") in ("running", "stopping")
                                                    and is_alive(status))


def _remove_folder(path: Path, what: str) -> None:
    try:
        shutil.rmtree(path)
    except OSError as e:
        raise HTTPException(500, f"Could not delete {what} completely: {e}. Close any program using its "
                                 f"files and try again.") from e


@app.delete("/api/runs/{name}")
def delete_run(name: str) -> dict:
    """Delete a run folder (results and transcripts). A running run must be stopped first."""
    d = _run_dir(name)
    status = read_status(d)
    if _run_is_active(name, status):
        hint = f" It is a Slurm job: scancel {status['slurm_job']}." if status.get("slurm_job") and not jobs.get(name) else ""
        raise HTTPException(409, f"This run is still running; stop it first.{hint}")
    _remove_folder(d, f"run {name}")
    log.info("Deleted run %s", name)
    return {"deleted": name}


@app.get("/api/runs/{name}")
def run_detail(name: str) -> dict:
    d = _run_dir(name)
    status = read_status(d)
    job = jobs.get(name)
    if status.get("state") in ("running", "stopping") and not (job and job.state == "running"):
        if is_alive(status):
            status["external"] = True        # running elsewhere (terminal or Slurm job); watch only
        else:
            status["state"] = "interrupted"  # its process is gone; it can be resumed
    return {"name": name, "status": status,
            "config": yaml.safe_load((d / "experiment.yaml").read_text(encoding="utf-8")),
            "plan": _read_json(d / "plan.json")}


@app.post("/api/runs/{name}/stop")
def stop_run(name: str) -> dict:
    d = _run_dir(name)
    status = read_status(d)
    if not jobs.get(name) and is_alive(status) and status.get("slurm_job"):
        raise HTTPException(409, f"This run is a Slurm job; stop it on the cluster with: scancel {status['slurm_job']}")
    job = jobs.get(name)
    if job and job.state == "running":
        job.stop.set()
        log.info("Run %s: stop requested", name)
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
            status = read_status(d)
            state = status.get("state")
            job = jobs.get(name)
            gone = (job is None or job.state != "running") and not is_alive(status) and idle > 2
            if state not in ("running", "created", "stopping") or gone:
                yield f"event: end\ndata: {json.dumps({'state': state})}\n\n"
                return
            idle = idle + 1 if len(lines) == sent else 0
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _row(r: dict) -> dict:
    return {k: r.get(k) for k in ("case_id", "stay_id", "persona", "reference_esi", "esi",
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
    return FileResponse(index, headers={"Cache-Control": "no-store"})
