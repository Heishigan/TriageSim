"""Case review: open individual cases from a built cohort and record a verdict."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from triagesim import paths
from triagesim.cohort.review import (VERDICTS, case_details, load_review, rebuild,
                                     sample_cases, save_verdict)
from triagesim.cohort.sources import DataLoadError, check_data
from triagesim.ui.common import cached_tables, files_signature, list_runs

st.title("Case review")
st.warning("This page shows patient-level data. Review it on this computer only; "
           "do not screenshot, copy or share it.", icon=":material/lock:")

data_dir = paths.data_dir()
output_dir = paths.output_dir()
checks = check_data(data_dir)
if not all(r.ok for r in checks):
    st.info("The data files are not all in place. Start with step 1 of **Cohort builder**.")
    st.stop()
runs = list_runs(output_dir)
if not runs:
    st.info("No saved cohorts yet. Build one in **Cohort builder** first.")
    st.stop()

run_dir = st.selectbox("Cohort", runs, format_func=lambda p: p.name)
try:
    tables = cached_tables(str(data_dir), files_signature(checks))
    run = rebuild(tables, run_dir)
except (DataLoadError, OSError, ValueError) as exc:
    st.error(f"Could not open this cohort: {exc}")
    st.stop()

if run.reproduced:
    st.success("Rebuilt from its saved settings: exactly the same cases as the saved cohort.")
else:
    st.error("Rebuilding from the saved settings gives different cases than the saved cohort. "
             "The data files may have changed since it was built.")

with st.expander("Filters and cohort flow"):
    st.markdown("\n".join(f"1. {line}" for line in run.settings.describe()) or "No filters.")
    report = json.loads((run_dir / "report.json").read_text()) if (run_dir / "report.json").is_file() else {}
    if report.get("flow"):
        st.table(pd.DataFrame(report["flow"]).rename(
            columns={"step": "Step", "ed_stays": "ED stays", "patients": "Patients"}))

# ---- Choose cases -----------------------------------------------------------------
c1, c2, c3 = st.columns([2, 1, 1])
steps = [s.step for s in run.result.flow[1:]]
group = c1.radio("Review", ["Included cases"] + [f"Excluded at: {s}" for s in steps],
                 help="Check included cases, or cases a specific filter removed.")
n = c2.number_input("How many", 1, 50, value=10)
seed = c3.number_input("Sample number", 1, 10_000, value=1,
                       help="Change it to draw a different sample. The same number gives the same cases.")

if group == "Included cases":
    pool = run.result.cohort["stay_id"]
else:
    step = group.removeprefix("Excluded at: ")
    pool = run.result.excluded.loc[run.result.excluded["excluded_at"] == step, "stay_id"]
st.caption(f"{len(pool):,} cases in this group.")
cases = sample_cases(pool, int(n), int(seed))

# ---- Cases ----------------------------------------------------------------------
review = load_review(run_dir).set_index("stay_id") if len(load_review(run_dir)) else pd.DataFrame()
for stay_id in cases:
    details = case_details(tables, run, stay_id)
    facts = details["facts"]
    done = review["verdict"].get(stay_id, "Not reviewed") if len(review) else "Not reviewed"
    with st.expander(f"Stay {stay_id}: {facts['Status']} | ESI {facts['Triage acuity (ESI)']} | "
                     f"{facts['Sex']}, {facts['Age at visit'].split(' ')[0]} | {done}"):
        st.table(pd.Series({k: str(v) for k, v in facts.items()}, name="Value"))
        st.markdown("**ED diagnoses** (rows that match the ICD filter are ticked)")
        st.dataframe(details["diagnoses"], hide_index=True, use_container_width=True)
        st.markdown("**All ED visits of this patient**")
        st.dataframe(details["visits"], hide_index=True, use_container_width=True)
        with st.form(f"verdict.{run_dir.name}.{stay_id}"):
            current = review["verdict"].get(stay_id, "Not reviewed") if len(review) else "Not reviewed"
            note_now = review["note"].get(stay_id, "") if len(review) else ""
            verdict = st.radio("Is this case filtered correctly?", VERDICTS, horizontal=True,
                               index=VERDICTS.index(current))
            note = st.text_input("Note (optional)", value="" if pd.isna(note_now) else str(note_now))
            if st.form_submit_button("Save verdict"):
                save_verdict(run_dir, stay_id, group, verdict, note)
                st.success("Saved.")

saved = load_review(run_dir)
if len(saved):
    st.subheader("Review so far")
    st.table(saved.groupby(["group", "verdict"]).size().rename("Cases").reset_index())
    st.caption(f"Saved in {run_dir / 'review.csv'}")
