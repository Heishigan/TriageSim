"""Drive the app headlessly: menu, the four-step cohort builder, case review."""
from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

APP = str(Path(__file__).resolve().parents[1] / "src/triagesim/ui/app.py")
BUILDER = "pages/cohort_builder.py"
REVIEW = "pages/case_review.py"


def open_page(page):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.switch_page(page).run()
    assert not at.exception
    return at


def click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception
    return at


def button(at, label):
    return next(b for b in at.button if b.label == label)


def step(at):
    return at.session_state["wizard.step"]


def build_preset(at, preset="elderly_falls"):
    click(at, "Next: choose filters")
    at.selectbox(key="w.preset").set_value(preset).run()
    click(at, "Next: review")
    click(at, "Build cohort")
    assert step(at) == 4
    return at


def test_home_page_opens():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception and at.title[0].value == "TriageSim"


def test_step1_blocks_until_files_are_in_place(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIAGESIM_DATA_DIR", str(tmp_path / "data"))
    at = open_page(BUILDER)
    assert step(at) == 1
    assert "patients.csv.gz" in at.code[0].value               # the layout tree is shown
    assert sum(":x:" in m.value for m in at.markdown) == 4
    assert button(at, "Next: choose filters").disabled
    assert (tmp_path / "data/hosp").is_dir()                   # empty folders created


def test_full_flow_shows_filters_and_exact_counts(app_dirs):
    at = open_page(BUILDER)
    assert any("All files are in place" in s.value for s in at.success)
    click(at, "Next: choose filters")
    assert step(at) == 2
    at.selectbox(key="w.preset").set_value("elderly_falls").run()
    assert at.text_input(key="w.elderly_falls.icd10_codes").value == "W00-W19"
    click(at, "Next: review")
    assert step(at) == 3
    review_text = " ".join(m.value for m in at.markdown)
    assert "ED diagnosis includes ICD-10 W00-W19 or ICD-9 E880-E888" in review_text
    click(at, "Build cohort")
    assert step(at) == 4
    assert "Age 65 or older at the ED visit" in " ".join(m.value for m in at.markdown)
    assert at.table[0].value["ED stays"].tolist() == [7, 6, 5, 4, 3, 2]
    assert len(list((app_dirs[1] / "cohorts").iterdir())) == 1


def test_filters_survive_going_back_and_forth(app_dirs):
    at = open_page(BUILDER)
    click(at, "Next: choose filters")
    at.selectbox(key="w.preset").set_value("elderly_falls").run()
    at.checkbox(key="w.elderly_falls.one_visit").uncheck().run()
    click(at, "Next: review")
    click(at, "Back")
    assert at.checkbox(key="w.elderly_falls.one_visit").value is False
    click(at, "Next: review")
    click(at, "Build cohort")
    assert at.table[0].value["ED stays"].tolist() == [7, 6, 5, 4, 3]


def test_invalid_filters_block_next(app_dirs):
    at = open_page(BUILDER)
    click(at, "Next: choose filters")
    at.text_input(key="w.(none).icd9_codes").set_value("W00-W19").run()
    assert any("ICD-9" in e.value for e in at.error)
    assert button(at, "Next: review").disabled


def test_no_filters_warns_on_review(app_dirs):
    at = open_page(BUILDER)
    click(at, "Next: choose filters")
    click(at, "Next: review")
    assert any("every ED stay" in w.value for w in at.warning)


def test_case_review(app_dirs):
    build_preset(open_page(BUILDER))
    at = open_page(REVIEW)
    assert any("exactly the same cases" in s.value for s in at.success)
    assert len(at.expander) == 1 + 2                 # flow + the 2 included cases
    at.radio[0].set_value("Excluded at: ICD code match in ED diagnoses").run()
    assert not at.exception
    assert any("1 cases in this group" in c.value for c in at.caption)


def test_review_without_cohorts(app_dirs):
    at = open_page(REVIEW)
    assert any("No saved cohorts" in i.value for i in at.info)


def test_filters_survive_switching_pages(app_dirs):
    at = open_page(BUILDER)
    click(at, "Next: choose filters")
    at.selectbox(key="w.preset").set_value("elderly_falls").run()
    at.text_input(key="w.elderly_falls.icd10_codes").set_value("W00-W19, S06").run()
    at.switch_page(REVIEW).run()
    at.switch_page(BUILDER).run()
    assert step(at) == 2
    assert at.selectbox(key="w.preset").value == "elderly_falls"
    assert at.text_input(key="w.elderly_falls.icd10_codes").value == "W00-W19, S06"


def test_later_step_without_settings_falls_back(app_dirs):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["wizard.step"] = 4
    at.run()
    at.switch_page(BUILDER).run()
    assert not at.exception and step(at) == 2


def test_no_streamlit_warnings_during_flow(app_dirs):
    at = build_preset(open_page(BUILDER))
    click(at, "Change filters")
    assert step(at) == 2
    texts = [w.value for w in at.warning] + [e.value for e in at.error]
    assert not any("Session State" in t or "default value" in t for t in texts)
