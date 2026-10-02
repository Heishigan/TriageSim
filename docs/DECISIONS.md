# Decisions

Newest at the bottom. If code and this file disagree, stop and ask Albert.

## Ground rules
- D1. No patient data in git. The UI and CLI show counts only. AI assistants work on
  code and invented test data; Albert runs and checks anything on real data.
- D2. Nothing is deleted without Albert's explicit permission.
- D3. Small steps, each explained, each with tests.

## Phase 1 MVP (2026-10-02)
- D4. New repository, separate from the thesis code (`../TriageSim`, used for reference only).
- D5. Scope: check the data, choose filters, build the cohort. Nothing else.
- D6. Filters: age, sex, admission, ICD codes in the ED diagnoses (ICD-9 and ICD-10,
  prefixes and ranges), acuity required, ESI levels, one visit per patient.
  Fixed order; each records ED stays and patients remaining.
- D7. Stack: Python >=3.10, pandas, PyYAML, Streamlit (local only), pytest. src layout.
- D8. Files are found by module folder and name anywhere under the data folder, so the
  PhysioNet download layout works without renaming. The check reads headers only.
- D9. Each build writes `outputs/<name>_<timestamp>/` with cohort.csv, settings.yaml, report.json.
- D10. Acceptance test: the elderly_falls preset must give exactly the same stays as the
  corrected thesis step 01 (`../TriageSim/pipeline/01_dataset_clean.py`) on real data.
  Note: the thesis cohort itself did not apply the fall filter, so the numbers will
  differ from the paper; that difference is the bug fix, not a mistake.

## One-click start and data folder (2026-10-02)
- D11. Target users include clinicians without a technical background. Model: ComfyUI /
  AI Toolkit (local server, opens in the browser).
- D12. Start by double-clicking `start-windows.bat` / `start-macos.command` / `start-linux.sh`.
  They install `uv`, which installs Python 3.12 (`.python-version`) and the pinned
  dependencies (`uv.lock`). No single .exe for now (large, fragile with Streamlit,
  antivirus false positives); an offline portable zip can be made at release.
- D13. Data is chosen as a folder (Browse button, system dialog), not uploaded through
  the browser: uploads copy every file each session and later note files exceed 1 GB.
  The app checks the folder on every start and remembers it in
  ~/.triagesim-cohort/preferences.json.
- D14. The app listens on localhost only, with Streamlit usage statistics off.
- D15. Data versions: MIMIC-IV v3.1 (11 Oct 2024) and MIMIC-IV-ED v2.2 (5 Jan 2023),
  still the latest on PhysioNet as of 2026-10-02.

## Rules and validation (2026-10-02)
- D16. `data/` and `outputs/` (and the user's real MIMIC folder) are off limits to AI
  assistants: no opening, listing, searching, copying or changing anything in them.
- D17. First real run (Albert, Windows, elderly_falls preset): 425,087 stays /
  205,504 patients -> age >=65: 133,397 -> admitted: 89,750 -> fall code: 8,901 ->
  ESI recorded: 8,626 -> first visit per patient: 7,475. ESI 1/2/3/4/5 =
  633/3,811/2,970/61/0; F 4,761, M 2,714. Total matches the published MIMIC-IV-ED size.
- D18. Validation added: ICD code shape per version (numeric ICD-9 codes in the ICD-10
  box are caught; ICD-9 E/V codes cannot be told apart from ICD-10 E/V chapters);
  type checks for preset files; incomplete downloads give a plain error naming the
  file; duplicate copies are reported; a filter leaving zero stays is flagged;
  unwritable output folders and same-second builds are handled.
- D19. Bug caught by tests: keyed form fields kept stale values when switching presets,
  silently dropping the ICD filter. Form field keys now include the preset name, and
  the UI test asserts every preset value reaches the applied settings.

## TriageSim app structure and case review (2026-10-02)
- D20. This repository becomes TriageSim itself; the cohort builder is one module. Thesis
  code moved to `Archive/TriageSim_thesis` (reference only). Package `triagesim`
  (cohort/, ui/), command `triagesim`, preferences in ~/.triagesim/.
- D21. The app has a menu: Home, Cohort builder, Case review. Simulation and evaluation
  are listed as "later" on Home, not as empty pages.
- D22. No separate Apply step: Build always uses exactly what is on screen, and the
  active filters are listed in plain words above the Build button. (A run with the
  preset selected but stale applied settings produced an unfiltered cohort.)
- D23. Every build records, for each excluded stay, the filter that removed it.
- D24. Case review shows patient-level data locally (Albert's request, for manual
  verification). It rebuilds a saved run from settings.yaml and checks the cases match
  cohort.csv; samples included or excluded-at-step cases with a seed; shows facts,
  all ED diagnoses (matches ticked) and all visits of the patient with reasons; saves
  verdicts to the run's review.csv (in outputs/, never committed).
- D25. ed/diagnosis now also needs `seq_num` and `icd_title` (for case review).
- D26. ED disposition (edstays.disposition) is shown in case review and saved in
  cohort.csv. Reason: a non-admitted ESI 1 fall looked suspicious, but without the
  disposition (e.g. transfer, death in the ED) it could not be judged. "Not admitted"
  means no admission to this hospital; it is not the same as "sent home".
