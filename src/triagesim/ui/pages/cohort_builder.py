"""Cohort builder: 1. data  2. filters  3. build. Shows counts only."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from triagesim import preferences
from triagesim.cohort.build import build_cohort, save_result
from triagesim.cohort.icd import parse_code_list
from triagesim.cohort.settings import ADMISSION_CHOICES, ESI_LEVELS, SEXES, CohortSettings
from triagesim.cohort.sources import DataLoadError, check_data
from triagesim.ui.common import PRESET_DIR, cached_tables, files_signature, remember, remembered

ADMISSION_LABELS = {"any": "Any", "admitted": "Admitted only", "not_admitted": "Not admitted only"}

st.title("Cohort builder")
st.caption("Choose which ED visits to study. Everything runs on this computer.")

# ---- Step 1: data -------------------------------------------------------------
st.header("1. Data")
data_dir = remembered("data_dir", "data")


def _browse() -> None:
    folder = preferences.pick_folder()
    if folder:
        st.session_state["data_dir"] = folder


with st.expander("How to get the data"):
    st.markdown(
        "1. Get credentialed access on [PhysioNet](https://physionet.org) and sign the "
        "data use agreements for MIMIC-IV and MIMIC-IV-ED.\n"
        "2. Download the files listed below.\n"
        "3. Put them in one folder. Keep PhysioNet's subfolders (`hosp`, `ed`); "
        "nested download folders are fine.\n"
        "4. Click **Browse** and choose that folder.\n\n"
        "The files stay on this computer. Nothing is uploaded."
    )

c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
typed = c1.text_input("MIMIC data folder", value=data_dir,
                      help="The folder where you put the PhysioNet downloads. "
                           "Subfolders are searched automatically.")
c2.button("Browse", on_click=_browse, use_container_width=True)
if typed != data_dir:
    st.session_state["data_dir"] = data_dir = typed

checks = check_data(data_dir)
for r in checks:
    if r.ok:
        st.markdown(f":white_check_mark: `{r.table.relative_path}`")
        if r.note:
            st.warning(r.note)
    else:
        st.markdown(f":x: `{r.table.relative_path}`: {r.message} "
                    f"[Download from {r.table.source}]({r.table.url})",
                    help=f"Place it as {r.table.relative_path} anywhere inside the data folder.")
data_ready = all(r.ok for r in checks)
if data_ready:
    st.success("All files found.")
    remember("data_dir", data_dir)
elif not Path(data_dir).is_dir():
    st.warning("This folder does not exist. Click Browse to choose your data folder.")

# ---- Step 2: filters ----------------------------------------------------------
st.header("2. Filters")
presets = sorted(PRESET_DIR.glob("*.yaml")) if PRESET_DIR.is_dir() else []
preset = st.selectbox("Start from a preset", ["(none)"] + [p.stem for p in presets], key="preset",
                      help="A preset fills in the filters below. You can change them afterwards.")
base = CohortSettings()
if preset != "(none)":
    try:
        base = CohortSettings.from_yaml(PRESET_DIR / f"{preset}.yaml")
    except (OSError, ValueError, TypeError) as exc:
        st.error(f"Preset '{preset}' could not be loaded: {exc}")


def key(field: str) -> str:
    # One set of fields per preset, so choosing a preset always shows its values.
    return f"form.{preset}.{field}"


name = st.text_input("Cohort name", value=base.name, key=key("name"),
                     help="Used to name the results folder. Letters, digits, - and _.")
c1, c2 = st.columns(2)
min_age = c1.number_input("Minimum age", 0, 120, value=base.min_age or 0, key=key("min_age"),
                          help="Age at the ED visit. 0 = no minimum.")
max_age = c2.number_input("Maximum age", 0, 120, value=base.max_age or 0, key=key("max_age"),
                          help="0 = no maximum. MIMIC reports ages above 89 as 91.")
sexes = st.multiselect("Sex", SEXES, default=base.sexes, key=key("sexes"))
admission = st.radio("Hospital admission", ADMISSION_CHOICES, horizontal=True, key=key("admission"),
                     index=ADMISSION_CHOICES.index(base.admission), format_func=ADMISSION_LABELS.get)
st.markdown("**ICD codes in the ED diagnoses.** Leave both empty for no code filter. "
            "Prefixes like `S06` or ranges like `W00-W19`, separated by commas.")
c1, c2 = st.columns(2)
icd10_text = c1.text_input("ICD-10", value=", ".join(base.icd10_codes), key=key("icd10_codes"),
                           help="ICD-10 codes start with a letter, e.g. W00-W19 or S06.")
icd9_text = c2.text_input("ICD-9", value=", ".join(base.icd9_codes), key=key("icd9_codes"),
                          help="ICD-9 codes start with a digit, E or V, e.g. E880-E888 or 850-854.")
require_acuity = st.checkbox("Require a triage acuity (ESI)", value=base.require_acuity,
                             key=key("require_acuity"))
esi_levels = st.multiselect("ESI levels", ESI_LEVELS, default=base.esi_levels, key=key("esi_levels"))
one_visit = st.checkbox("One visit per patient (first qualifying visit)",
                        value=base.one_visit_per_patient, key=key("one_visit"),
                        help="Keeps each patient once, so no patient counts twice.")

settings, problem = None, None
try:
    settings = CohortSettings(
        name=name.strip(), min_age=int(min_age) or None, max_age=int(max_age) or None,
        sexes=list(sexes), admission=admission,
        icd10_codes=parse_code_list(icd10_text, 10), icd9_codes=parse_code_list(icd9_text, 9),
        require_acuity=require_acuity, esi_levels=sorted(esi_levels),
        one_visit_per_patient=one_visit)
    settings.validate()
except ValueError as exc:
    settings, problem = None, str(exc)

# ---- Step 3: build ------------------------------------------------------------
st.header("3. Build cohort")
output_dir = remembered("output_dir", "outputs")
typed_out = st.text_input("Save results in", value=output_dir)
if typed_out != output_dir:
    st.session_state["output_dir"] = output_dir = typed_out

if problem:
    st.error(problem)
elif settings is not None:
    lines = settings.describe()
    if lines:
        st.markdown("**Filters that will be applied:**\n" + "\n".join(f"1. {line}" for line in lines))
    else:
        st.warning("No filters selected: the cohort will contain every ED stay.")

if not data_ready:
    st.info("Add the data files first (step 1).")
elif st.button("Build cohort", type="primary", disabled=settings is None):
    try:
        result = build_cohort(cached_tables(data_dir, files_signature(checks)), settings)
        run_dir = save_result(result, settings, output_dir, data_dir)
    except DataLoadError as exc:
        st.error(str(exc))
        st.stop()
    except OSError as exc:
        st.error(f"Could not save the results in '{output_dir}': {exc}. Choose another folder.")
        st.stop()
    remember("output_dir", output_dir)
    for step in result.empty_steps()[:1]:
        st.warning(f"No ED stays are left after '{step}'. Check that filter.")
    summary = result.summary()
    st.subheader("Cohort flow")
    st.table(pd.DataFrame(summary["flow"]).rename(
        columns={"step": "Step", "ed_stays": "ED stays", "patients": "Patients"}))
    c1, c2 = st.columns(2)
    c1.markdown("**ESI distribution**")
    c1.table(pd.Series(summary["esi_distribution"], name="Stays"))
    c2.markdown("**Sex**")
    c2.table(pd.Series(summary["sex_distribution"], name="Stays"))
    st.success(f"Saved to {run_dir}. Open **Case review** in the menu to check individual cases.")
