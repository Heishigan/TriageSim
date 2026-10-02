import streamlit as st

st.title("TriageSim")
st.markdown(
    "A testbed for evaluating how language models triage emergency department patients, "
    "using MIMIC-IV. Everything runs on this computer; no data leaves it."
)
st.subheader("Modules")
st.markdown(
    "- **Cohort builder**: choose which ED visits to study (age, sex, admission, ICD codes, "
    "triage acuity) and see how many remain after each filter.\n"
    "- **Case review**: open individual cases from a built cohort to check that the "
    "filters worked, and record your verdict.\n"
    "- *Simulation and evaluation: coming in a later version.*"
)
st.info("Start with **Cohort builder** in the menu on the left.")
