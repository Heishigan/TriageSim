# TriageSim

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23777546.svg)](https://doi.org/10.5281/zenodo.23777546)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An open-source testbed for evaluating how language models triage emergency department
patients, built on MIMIC-IV. Build a cohort, turn it into cases, configure agents
(nurse, patient, evaluator) and their models, watch the conversations live, and read
the results. Everything runs on your own computer or your own server; no data leaves it.

## How it works

TriageSim turns ED records into case files and lets a Nurse Agent assign an Emergency
Severity Index (ESI) level, either by reading the record or by interviewing a Patient Agent
that knows only what the patient would know. An Evaluator Agent scores each interview. The
ESI level the triage nurse recorded is the reference: under-triage means a less urgent level
than the triage nurse assigned, over-triage a more urgent one.

## Requirements

- Windows, macOS or Linux; internet for the first start.
- [Ollama](https://ollama.com) for the language models. Small models (3-8B) run on a laptop;
  the accompanying paper used 27B, 12B and 20B models on one 46 GB GPU.
- Credentialed PhysioNet access to MIMIC-IV 3.1, MIMIC-IV-ED 2.2 and MIMIC-IV-Note 2.2,
  or the demo mode with invented data.

## Get TriageSim

```bash
git clone https://github.com/Heishigan/TriageSim.git
```

or "Code > Download ZIP" on GitHub.

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
(temperature 0.7), seed 42, 12-question limit, 20 cases stratified by ESI level.

Two variations of chart review are set in the New experiment form or in the YAML file:

- **Arrival information only**: the nurse sees only the arrival information (chief
  complaint, vital signs, arrival mode), without the history.
- **Retrieved similar cases**: the nurse also sees 40 earlier patients with similar
  complaints and vital signs and their ESI levels, from a pool outside the sample
  (embedding model `nomic-embed-text`).

## Command line

```bash
uv run triagesim cohort build --settings configs/cohorts/elderly_falls.yaml
uv run triagesim cases build --cohort outputs/cohorts/<cohort folder>
uv run triagesim models pull --experiment configs/experiments/interview.yaml
uv run triagesim run --experiment configs/experiments/interview.yaml
uv run triagesim run --resume outputs/runs/<run folder>
```

An experiment designed in the app can be downloaded as YAML ("Download YAML") and run
the same way. A stopped run can be resumed; on a server, the app can be opened from another
computer by setting `TRIAGESIM_ACCESS_TOKEN`.

## Outputs

```
outputs/cohorts/<name>_<time>/  cohort.csv, settings.yaml, report.json,
                                cases.jsonl, cases_report.json, review.csv
outputs/runs/<name>_<time>/     experiment.yaml, plan.json, status.json,
                                events.jsonl (live log), results.jsonl
```

Files containing patient-level data (`cohort.csv`, `cases.jsonl`, `review.csv`,
`events.jsonl`, `results.jsonl`) must not be shared.

## Privacy

Everything runs locally. The model catalog lists no cloud models, and MIMIC data must never
be sent to online AI services (PhysioNet data use agreement).

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
(built front end); `frontend/` (React source); `configs/`; `tests/`.

## Reproducing the paper

`paper/` holds the experiment settings of the six conditions in the accompanying paper
(chart review, multiple-choice vignette, arrival information only, retrieved similar cases,
interview, interview with personas) and the script for its statistics. See
[`paper/README.md`](paper/README.md).

## Related publication

Pathmaraj H, Quintero L, Viswanathan V. TriageSim: A Multi-Agent Framework for Evaluating
LLM Clinical Reasoning in Emergency Triage of Older Adults. Under review; reference to follow.

## Citation

If you use TriageSim, please cite it (see `CITATION.cff`, or "Cite this repository" on GitHub).

## License

MIT (see `LICENSE`). MIMIC-IV data are not included and remain subject to the PhysioNet
credentialed data use agreement.
