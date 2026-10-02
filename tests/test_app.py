"""Drive the app headlessly: menu, cohort builder, case review."""
from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

APP = str(Path(__file__).resolve().parents[1] / "src/triagesim/ui/app.py")
BUILDER = "pages/cohort_builder.py"
REVIEW = "pages/case_review.py"


@pytest.fixture(autouse=True)
def isolated_prefs(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIAGESIM_HOME", str(tmp_path / "home"))


def open_page(page, data_dir, output_dir=None):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["data_dir"] = str(data_dir)
    if output_dir:
        at.session_state["output_dir"] = str(output_dir)
    at.run()
    at.switch_page(page).run()
    assert not at.exception
    return at


def build_preset(at):
    at.selectbox(key="preset").set_value("elderly_falls").run()
    at.button[-1].click().run()                      # Build cohort
    assert not at.exception


def test_home_page_opens():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception and at.title[0].value == "TriageSim"


def test_missing_data_shows_guidance(tmp_path):
    at = open_page(BUILDER, tmp_path / "nowhere")
    assert any("does not exist" in w.value for w in at.warning)
    assert sum(":x:" in m.value for m in at.markdown) == 4


def test_preset_builds_exact_flow_and_remembers_folders(data_dir, tmp_path):
    out = tmp_path / "out"
    at = open_page(BUILDER, data_dir, out)
    assert any("All files found" in s.value for s in at.success)
    at.selectbox(key="preset").set_value("elderly_falls").run()
    # Every preset value reaches the fields, including the ICD codes.
    assert at.text_input(key="form.elderly_falls.icd10_codes").value == "W00-W19"
    assert any("ED diagnosis includes ICD-10 W00-W19 or ICD-9 E880-E888" in m.value for m in at.markdown)
    at.button[-1].click().run()
    assert any("Saved to" in s.value for s in at.success)
    assert at.table[0].value["ED stays"].tolist() == [7, 6, 5, 4, 3, 2]

    from triagesim import preferences
    assert preferences.load() == {"data_dir": str(data_dir), "output_dir": str(out)}


def test_what_you_see_is_what_is_built(data_dir, tmp_path):
    """Editing a field after choosing a preset changes the build (no hidden Apply step)."""
    at = open_page(BUILDER, data_dir, tmp_path / "out")
    at.selectbox(key="preset").set_value("elderly_falls").run()
    at.checkbox(key="form.elderly_falls.one_visit").uncheck().run()
    at.button[-1].click().run()
    assert at.table[0].value["ED stays"].tolist() == [7, 6, 5, 4, 3]


def test_wrong_icd_box_blocks_build(data_dir):
    at = open_page(BUILDER, data_dir)
    at.text_input(key="form.(none).icd9_codes").set_value("W00-W19").run()
    assert any("ICD-9" in e.value for e in at.error)
    assert at.button[-1].disabled


def test_no_filters_warns(data_dir):
    at = open_page(BUILDER, data_dir)
    assert any("every ED stay" in w.value for w in at.warning)


def test_case_review(data_dir, tmp_path):
    out = tmp_path / "out"
    build_preset(open_page(BUILDER, data_dir, out))

    at = open_page(REVIEW, data_dir, out)
    assert any("exactly the same cases" in s.value for s in at.success)
    assert len(at.expander) == 1 + 2                 # flow + the 2 included cases
    at.radio[0].set_value("Excluded at: ICD code match in ED diagnoses").run()
    assert not at.exception
    assert any("1 cases in this group" in c.value for c in at.caption)


def test_review_without_cohorts(data_dir, tmp_path):
    at = open_page(REVIEW, data_dir, tmp_path / "empty")
    assert any("No saved cohorts" in i.value for i in at.info)
