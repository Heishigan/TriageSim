# TriageSim

A testbed for evaluating how language models triage emergency department patients,
using MIMIC-IV. It runs on your own computer as a small app in your browser.

| Module | Status |
|---|---|
| **Cohort builder**: choose which ED visits to study and see the cohort flow | ready |
| **Case review**: open single cases to verify the filters and record a verdict | ready |
| Simulation and evaluation | later |

## Start

Double-click the start file for your system:

| System | File |
|---|---|
| Windows | `start-windows.bat` |
| macOS | `start-macos.command` |
| Linux | `start-linux.sh` |

The first start installs everything it needs, including Python, and takes a few
minutes (internet required). Later starts take seconds. The app opens in your browser
and is reachable from this computer only. Close the black window to stop it.

## Data

MIMIC data requires credentialed access on PhysioNet and signed data use agreements.
Put these four files in the `data` folder of TriageSim, exactly like this
(the app creates the empty `hosp` and `ed` folders on first start):

```
TriageSim/data/
├── ed/
│   ├── edstays.csv.gz
│   ├── triage.csv.gz
│   └── diagnosis.csv.gz
└── hosp/
    └── patients.csv.gz
```

| File | PhysioNet project |
|---|---|
| `hosp/patients.csv.gz` | [MIMIC-IV v3.1](https://physionet.org/content/mimiciv/3.1/) |
| `ed/edstays.csv.gz`, `ed/triage.csv.gz`, `ed/diagnosis.csv.gz` | [MIMIC-IV-ED v2.2](https://physionet.org/content/mimic-iv-ed/2.2/) |

Keep the files compressed and do not rename them. If a file is in the wrong place, the
app tells you where it found it and where to move it. `data/` and `outputs/` are
never committed to git.

## Use

**Cohort builder** (menu on the left) walks you through four steps. Each step must be
complete before the next one opens.

1. **Data**: shows the required layout and checks every file.
2. **Filters**: start from a preset or set your own; invalid values block the next step.
3. **Review**: the filters that will run, in plain words. Click **Build cohort**.
4. **Results**: the filters applied, the cohort flow, ESI and sex counts. Results are
   saved to `outputs/`.

**Case review**: open single cases to verify the filters and record a verdict | ready |
| Simulation and evaluation | later |

## Start

Double-click the start file for your system:

| System | File |
|---|---|
| Windows | `start-windows.bat` |
| macOS | `start-macos.command` |
| Linux | `start-linux.sh` |

The first start installs everything it needs, including Python, and takes a few
minutes (internet required). Later starts take seconds. The app opens in your browser
and is reachable from this computer only. Close the black window to stop it.

## Data

MIMIC data requires credentialed access on PhysioNet and signed data use agreements.
Put these four files in the `data` folder of TriageSim, exactly like this
(the app creates the empty `hosp` and `ed` folders on first start):

```
TriageSim/data/
├── ed/
│   ├── edstays.csv.gz
│   ├── triage.csv.gz
│   └── diagnosis.csv.gz
└── hosp/
    └── patients.csv.gz
```

| File | PhysioNet project |
|---|---|
| `hosp/patients.csv.gz` | [MIMIC-IV v3.1](https://physionet.org/content/mimiciv/3.1/) |
| `ed/edstays.csv.gz`, `ed/triage.csv.gz`, `ed/diagnosis.csv.gz` | [MIMIC-IV-ED v2.2](https://physionet.org/content/mimic-iv-ed/2.2/) |

Keep the files compressed and do not rename them. If a file is in the wrong place, the
app tells you where it found it and where to move it. `data/` and `outputs/` are
never committed to git.

## Use

**Cohort builder** (menu on the left)

1. **Data**: choose your data folder; every file should show a green tick.
2. **Filters**: start from a preset or set your own. The filters that will run are
   listed in plain words above the Build button.
3. **Build**: see the cohort flow; results are saved to `outputs/`.

**Case review** shows patient-level data, on this computer only.

- Pick a saved cohort. The app rebuilds it from its settings and confirms it gets
  exactly the same cases.
- Draw a random sample of included cases, or of cases removed by a specific filter.
  The same sample number always gives the same cases.
- Each case shows its facts (age calculation, ESI, admission), all its ED diagnoses with
  the matching codes ticked, and all ED visits of that patient with the reason each
  one was kept or removed.
- Record a verdict (correct, incorrect, unsure) and a note. Verdicts are saved in the
  run's folder as `review.csv`.

Command line (optional, for scripting):

```bash
uv run triagesim cohort check
uv run triagesim cohort build --settings configs/elderly_falls.yaml
```

## Filters

Applied in this order; each one is optional.

| Filter | Options |
|---|---|
| Age at the ED visit | minimum, maximum |
| Sex | F, M |
| Hospital admission | any, admitted only, not admitted only |
| ICD codes in the ED diagnoses | ICD-10 and ICD-9 prefixes (`S06`) or ranges (`W00-W19`) |
| Triage acuity | require an ESI value; choose ESI levels 1-5 |
| One visit per patient | keep the first qualifying visit |

Age at the visit is `anchor_age + (year of ED arrival − anchor_year)`. MIMIC reports
ages above 89 as 91. ICD codes are matched without dots, as MIMIC stores them.

## Output

Each build creates `outputs/<name>_<timestamp>/`:

| File | Contents | Share? |
|---|---|---|
| `cohort.csv` | one row per ED stay | **No**: patient data |
| `settings.yaml` | the filters used; rerun with `build --settings` | yes |
| `report.json` | cohort flow, ESI and sex distribution | yes |
| `review.csv` | your case review verdicts (if any) | **No**: contains stay ids |

## Presets

`configs/elderly_falls.yaml`: patients 65 or older, admitted through the ED with a
fall code (ICD-10 W00-W19, ICD-9 E880-E888), ESI recorded, first visit per patient.

## Development

```bash
uv run --extra dev pytest          # tests use small invented tables, no real data
```

Layout:

```
src/triagesim/
  cli.py            command line and the app launcher
  paths.py          fixed folders: data/, outputs/, configs/
  cohort/           icd.py, settings.py, sources.py, build.py, review.py
  ui/               app.py (menu), common.py, pages/ (home, cohort_builder, case_review)
configs/            filter presets
tests/              invented test data only
docs/DECISIONS.md   design decisions
```
