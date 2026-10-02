"""TriageSim app entry point: page setup and the menu."""
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="TriageSim", layout="wide")

PAGES = Path(__file__).parent / "pages"
menu = st.navigation({
    "TriageSim": [st.Page(PAGES / "home.py", title="Home", default=True)],
    "Cohort": [st.Page(PAGES / "cohort_builder.py", title="Cohort builder"),
               st.Page(PAGES / "case_review.py", title="Case review")],
})
menu.run()
