"""Cohort builder as a four-step flow: Data -> Filters -> Review -> Results.

Only one step is shown at a time, and the next step unlocks only when the current
one is complete. Only counts are shown, never patient rows.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from triagesim import paths
from triagesim.cohort.build import build_cohort, save_result
from triagesim.cohort.icd import parse_code_list
from triagesim.cohort.settings import ADMISSION_CHOICES, ESI_LEVELS, SEXES, CohortSettings
from triagesim.cohort.sources import DataLoadError, check_data, ensure_layout, layout_tree
from triagesim.ui.common import cached_tables, files_signature, open_folder

STEPS = ("Data", "Filters", "Review", "Results")
ADMISSION_LABELS = {"any": "Any", "admitted": "Admitted only", "not_admitted": "Not admitted only"}

data_dir = paths.data_dir()
output_dir = paths.output_dir()
st.session_state.setdefault("wizard.step", 1)


def go(step: int) -> None:
    st.session_state["wizard.step"] = step


def kept(name: str, default):
    """Widget key whose value survives leaving this step.

    Streamlit clears a widget's value when the widget is not on screen. The value
    is therefore also kept under 'keep.<name>' and copied back before the widget
    is drawn; ``on_change=save`` updates the kept copy when the user edits it.
    """
    st.session_state.setdefault(f"keep.{name}", default)
    st.session_state[f"w.{name}"] = st.session_state[f"keep.{name}"]
    return f"w.{name}"


def save(name: str) -> None:
    st.session_state[f"keep.{name}"] = st.session_state[f"w.{name}"]


def flow_table(flow: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(flow).rename(columns={"step": "Step", "ed_stays": "ED stays", "patients": "Patients"})


st.title("Cohort builder")
# A later step without what it needs (e.g. after a restart) falls back to the right step.
if st.session_state["wizard.step"] >= 3 and "wizard.settings" not in st.session_state:
    go(2)
if st.session_state["wizard.step"] == 4 and "wizard.summary" not in st.session_state:
    go(3)
step = st.session_state["wizard.step"]
st.progress((step - 1) / (len(STEPS) - 1))
st.markdown("  →  ".join(f"**{i}. {name}**" if i == step else
                         (f"{i}. {name} ✓" if i < step else f"{i}. {name}")
                         for i, name in enumerate(STEPS, start=1)))
st.divider()

# ---- Step 1: data ------------------------------------------------------------------
if step == 1:
    st.header("Step 1: Place the MIMIC files")
    ensure_layout(data_dir)
    st.markdown("Put the four files below in the **data** folder inside TriageSim, exactly like this:")
    st.code(layout_tree("TriageSim/data"), language=None)
    st.caption(f"The data folder on this computer: {data_dir}")
    c1, c2 = st.columns(2)
    if c1.button("Open the data folder", use_container_width=True):
        open_folder(data_dir)
    c2.button("Check again", use_container_width=True)

    with st.expander("Where do I get these files?"):
        st.markdown(
            "1. Get credentialed access on [PhysioNet](https://physionet.org) and sign the "
            "data use agreements for MIMIC-IV and MIMIC-IV-ED.\n"
            "2. Download `patients.csv.gz` from the **hosp** folder of "
            "[MIMIC-IV v3.1](https://physionet.org/content/mimiciv/3.1/), and `edstays.csv.gz`, "
            "`triage.csv.gz` and `diagnosis.csv.gz` from the **ed** folder of "
            "[MIMIC-IV-ED v2.2](https://physionet.org/content/mimic-iv-ed/2.2/).\n"
            "3. Keep the files compressed (`.csv.gz`). Do not rename them.\n\n"
            "The files stay on this computer. Nothing is uploaded."
        )

    checks = check_data(data_dir)
    for r in checks:
        if r.ok:
            st.markdown(f":white_check_mark: `data/{r.table.relative_path}`")
        else:
            st.markdown(f":x: `data/{r.table.relative_path}`: {r.message}")
    data_ready = all(r.ok for r in checks)
    if data_ready:
        st.success("All files are in place.")
    else:
        st.info("Place the missing files, then click **Check again**.")
    st.button("Next: choose filters", type="primary", disabled=not data_ready, on_click=go, args=(2,))

# ---- Step 2: filters ---------------------------------------------------------------
elif step == 2:
    st.header("Step 2: Choose the filters")
    presets = sorted(paths.CONFIG_DIR.glob("*.yaml")) if paths.CONFIG_DIR.is_dir() else []
    preset = st.selectbox("Start from a preset", ["(none)"] + [p.stem for p in presets],
                          key=kept("preset", "(none)"), on_change=save, args=("preset",),
                          help="A preset fills in the filters below. You can change them afterwards.")
    base = CohortSettings()
    if preset != "(none)":
        try:
            base = CohortSettings.from_yaml(paths.CONFIG_DIR / f"{preset}.yaml")
        except (OSError, ValueError, TypeError) as exc:
            st.error(f"Preset '{preset}' could not be loaded: {exc}")

    def field(name: str, default) -> dict:
        # One set of values per preset, so choosing a preset always shows its values.
        full = f"{preset}.{name}"
        return {"key": kept(full, default), "on_change": save, "args": (full,)}

    name = st.text_input("Cohort name", **field("name", base.name),
                         help="Used to name the results folder. Letters, digits, - and _.")
    c1, c2 = st.columns(2)
    min_age = c1.number_input("Minimum age", 0, 120, **field("min_age", base.min_age or 0),
                              help="Age at the ED visit. 0 = no minimum.")
    max_age = c2.number_input("Maximum age", 0, 120, **field("max_age", base.max_age or 0),
                              help="0 = no maximum. MIMIC reports ages above 89 as 91.")
    sexes = st.multiselect("Sex", SEXES, **field("sexes", base.sexes))
    admission = st.radio("Hospital admission", ADMISSION_CHOICES, horizontal=True,
                         **field("admission", base.admission), format_func=ADMISSION_LABELS.get)
    st.markdown("**ICD codes in the ED diagnoses.** Leave both empty for no code filter. "
                "Prefixes like `S06` or ranges like `W00-W19`, separated by commas.")
    c1, c2 = st.columns(2)
    icd10_text = c1.text_input("ICD-10", **field("icd10_codes", ", ".join(base.icd10_codes)),
                               help="ICD-10 codes start with a letter, e.g. W00-W19 or S06.")
    icd9_text = c2.text_input("ICD-9", **field("icd9_codes", ", ".join(base.icd9_codes)),
                              help="ICD-9 codes start with a digit, E or V, e.g. E880-E888 or 850-854.")
    require_acuity = st.checkbox("Require a triage acuity (ESI)",
                                 **field("require_acuity", base.require_acuity))
    esi_levels = st.multiselect("ESI levels", ESI_LEVELS, **field("esi_levels", base.esi_levels))
    one_visit = st.checkbox("One visit per patient (first qualifying visit)",
                            **field("one_visit", base.one_visit_per_patient),
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
    if problem:
        st.error(problem)

    def to_review() -> None:
        st.session_state["wizard.settings"] = settings
        go(3)

    c1, c2 = st.columns([1, 3])
    c1.button("Back", on_click=go, args=(1,), use_container_width=True)
    c2.button("Next: review", type="primary", disabled=settings is None, on_click=to_review,
              use_container_width=True)

# ---- Step 3: review and build ----------------------------------------------------
elif step == 3:
    st.header("Step 3: Review and build")
    settings: CohortSettings = st.session_state["wizard.settings"]
    st.markdown(f"**Cohort name:** {settings.name}")
    lines = settings.describe()
    if lines:
        st.markdown("**Filters that will be applied, in this order:**\n"
                    + "\n".join(f"1. {line}" for line in lines))
    else:
        st.warning("No filters selected: the cohort will contain every ED stay.")
    st.caption(f"Results will be saved in {output_dir}")

    c1, c2 = st.columns([1, 3])
    c1.button("Back", on_click=go, args=(2,), use_container_width=True)
    if c2.button("Build cohort", type="primary", use_container_width=True):
        checks = check_data(data_dir)
        if not all(r.ok for r in checks):
            st.error("Some data files are no longer in place. Go back to step 1.")
            st.stop()
        try:
            result = build_cohort(cached_tables(str(data_dir), files_signature(checks)), settings)
            run_dir = save_result(result, settings, output_dir, data_dir)
        except DataLoadError as exc:
            st.error(str(exc))
            st.stop()
        except OSError as exc:
            st.error(f"Could not save the results in '{output_dir}': {exc}.")
            st.stop()
        st.session_state["wizard.summary"] = result.summary()
        st.session_state["wizard.run_dir"] = str(run_dir)
        st.session_state["wizard.empty_steps"] = result.empty_steps()
        go(4)
        st.rerun()

# ---- Step 4: results ------------------------------------------------------------
else:
    st.header("Step 4: Results")
    settings = st.session_state["wizard.settings"]
    summary = st.session_state["wizard.summary"]
    for empty in st.session_state["wizard.empty_steps"][:1]:
        st.warning(f"No ED stays are left after '{empty}'. Check that filter.")
    st.markdown(f"**Cohort:** {settings.name}")
    st.markdown("**Filters applied:**\n" + ("\n".join(f"1. {line}" for line in settings.describe())
                                            or "None: every ED stay."))
    st.subheader("Cohort flow")
    st.table(flow_table(summary["flow"]))
    c1, c2 = st.columns(2)
    c1.markdown("**ESI distribution**")
    c1.table(pd.Series(summary["esi_distribution"], name="Stays"))
    c2.markdown("**Sex**")
    c2.table(pd.Series(summary["sex_distribution"], name="Stays"))
    st.success(f"Saved to {st.session_state['wizard.run_dir']}")

    c1, c2, c3 = st.columns(3)
    c1.page_link("pages/case_review.py", label="Review cases", icon=":material/fact_check:")
    c2.button("Change filters", on_click=go, args=(2,), use_container_width=True)
    c3.button("Start over", on_click=go, args=(1,), use_container_width=True)
