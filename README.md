# TriageSim

An open-source testbed for evaluating how language models triage emergency department
patients, built on MIMIC-IV. Build a cohort, turn it into cases, configure agents
(nurse, patient, evaluator) and their models, watch the conversations live, and read
the results. Everything runs on your own computer or your own cluster.

## Start

Double-click the start file for your system. The first start installs everything,
including Python (a few minutes, internet needed); later starts take seconds.

| | Real data | Demo (invented data, safe to show) |
|---|---|---|
| Windows | `start-windows.bat` | `start-demo-windows.bat` |
| macOS / Linux | `start-macos.command` / `start-linux.sh` | `uv run triagesim ui --demo` |

The app opens in your browser and is reachable from this computer only.
Models run in [Ollama](https://ollama.com), which must be installed separately.

## The five steps (menu on the left)

1. **Data**: place the MIMIC files in `data/` (layout shown below and in the app).
2. **Cohorts & cases**: choose which ED visits to study (age, sex, admission, ICD codes,
   ESI, one visit per patient), see the cohort flow, review single cases, then build
   **case files**: what the nurse sees at arrival, what the patient knows (the HPI with
   ED course, imaging, results and treatment removed; history; home medications) and
   the reference answers (nurse ESI, disposition, head-injury label).
3. **Models**: download models from the Ollama library or GGUF files from Hugging Face
   (with your token for gated models), and test them.
4. **New experiment**: start from a preset and adjust each agent's model, prompt and what
   it may read. Prompts can only use fields the agent is allowed to see; the nurse and
   patient can never see the answers.
5. **Runs & results**: watch conversations live, stop and resume, then see agreement,
   under- and over-triage, head-injury under-triage, evaluator scores and per-persona results, with 95% Wilson intervals, paired McNemar comparisons
   between runs and a plain-language summary written by a model.

## Data

MIMIC requires credentialed PhysioNet access and signed data use agreements.

```
TriageSim/data/
├── ed/          edstays, triage, diagnosis, medrecon (.csv.gz)   MIMIC-IV-ED v2.2
├── hosp/        patients, diagnoses_icd (.csv.gz)                MIMIC-IV v3.1
└── note/        discharge.csv.gz                                 MIMIC-IV-Note v2.2
```

`hosp/diagnoses_icd` is optional (head-injury label). `data/`, `outputs/` and `demo/`
are never committed to git.

## Experiment presets (`configs/experiments/`)

| Preset | What happens |
|---|---|
| `interview` | The nurse interviews a simulated patient. In the form: the patient type (language model in character, or retrieval only, answering from retrieved passages of its record) and the persona (neutral, one fixed persona, or `random` per case: stoic, anxious, confused, cooperative) |
| `chart_review` | The nurse reads the chart and decides, no conversation |
| `multiple_choice` | The same information as a board-style question |

Defaults: nurse and evaluator `qwen2.5:32b` (temperature 0), patient `llama3.1:8b`
(temperature 0.7), seed 42, 12-question limit, 20 random cases.

## Cluster (command line)

```bash
uv run triagesim cohort build --settings configs/cohorts/elderly_falls.yaml
uv run triagesim cases build --cohort outputs/cohorts/<cohort folder>
uv run triagesim models pull --experiment configs/experiments/interview.yaml
uv run triagesim run --experiment configs/experiments/interview.yaml
uv run triagesim run --resume outputs/runs/<run folder>
```

An experiment designed in the app can be downloaded as YAML ("Download YAML") and run
the same way. A run stops cleanly at a Slurm time limit and can be resumed.

## Outputs

```
outputs/cohorts/<name>_<time>/  cohort.csv, settings.yaml, report.json,
                                cases.jsonl, cases_report.json, review.csv
outputs/runs/<name>_<time>/     experiment.yaml, plan.json, status.json,
                                events.jsonl (live log), results.jsonl
```

Files containing patient-level data (`cohort.csv`, `cases.jsonl`, `review.csv`,
`events.jsonl`, `results.jsonl`) must not be shared.

## Development

```bash
uv run --extra dev pytest          # tests use invented data only
uv run triagesim ui --demo --no-browser &   # then, with Playwright installed:
python scripts/browser_test.py http://127.0.0.1:8765   # clicks through the whole app
cd frontend && npm install && npm run build   # rebuilds src/triagesim/web/
```

Layout: `src/triagesim/` with `cohort/` (filters, review), `cases/` (case files,
redaction), `llm/` (Ollama, Hugging Face, demo model), `experiment/` (config, agents,
LangGraph engine, runs), `results/` (metrics, summary), `server/` (FastAPI) and `web/`
(built front end); `frontend/` (React source); `configs/`; `tests/`; `docs/DECISIONS.md`.
