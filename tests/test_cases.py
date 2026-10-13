import json

from triagesim.cases.build import CaseSettings, build_cases, load_cases, save_cases, summarize
from triagesim.cases.notes import redact_hpi, split_sections
from triagesim.cohort.build import build_cohort
from triagesim.cohort.settings import CohortSettings

from conftest import NOTE_11


def cohort(tables):
    return build_cohort(tables, CohortSettings.from_yaml("configs/elderly_falls.yaml")).cohort


# ---- Sections and redaction ------------------------------------------------------
def test_split_sections():
    s = split_sections(NOTE_11)
    assert s["hpi"].startswith("Ms. ___ is a 70 year old woman")
    assert s["past_medical_history"] == "Atrial fibrillation, hypertension"
    assert s["allergies"] == "Penicillins"
    assert "hospital_course" in s and "subdural" in s["hospital_course"]


def test_redaction_removes_results_and_ed_course_but_keeps_history():
    red = redact_hpi(split_sections(NOTE_11)["hpi"])
    assert "tripped over a rug" in red.text and "apixaban" in red.text
    assert "denies loss of consciousness" in red.text
    for leaked in ["CT", "subdural", "initial vitals", "ondansetron", "neurosurgery"]:
        assert leaked not in red.text
    assert red.ed_course_cut and red.removed == {"imaging": 1}


def test_fall_history_is_not_mistaken_for_results():
    hpi = "She was found on the floor by her daughter. She is negative for chest pain and was found down."
    assert redact_hpi(hpi).text == hpi and not redact_hpi(hpi).changed


def test_outside_hospital_imaging_is_removed():
    hpi = ("Mr. ___ fell down stairs. He was taken to ___ where a head CT revealed a bleed. "
           "He was transferred to ___ for evaluation. He takes warfarin.")
    red = redact_hpi(hpi)
    assert red.text == "Mr. ___ fell down stairs. He takes warfarin."


# ---- Case files ----------------------------------------------------------------------
def test_cases_keep_views_apart(tables, case_tables, notes):
    cases, flow = build_cases(cohort(tables), case_tables, notes, CaseSettings())
    assert [c["stay_id"] for c in cases] == [11]           # stay 61 has no HPI section
    assert flow == [{"step": "Cohort cases", "cases": 2}, {"step": "Discharge note found", "cases": 2},
                    {"step": "HPI section found", "cases": 1}]
    c = cases[0]
    assert c["patient_view"]["medications"] == ["Apixaban", "Lisinopril"]
    assert c["patient_view"]["allergies"] == "Penicillins"
    assert "subdural" not in json.dumps(c["patient_view"])  # no leakage into what the patient knows
    assert "esi" not in c["patient_view"] and "esi" not in c["nurse_view"]
    assert c["nurse_view"]["vitals"]["heartrate"] == 80
    assert c["nurse_view"]["arrival_transport"] == "AMBULANCE"
    assert c["reference"] == {"esi": 2, "disposition": "ADMITTED", "admitted": True, "head_injury_icd": True}
    assert c["audit"]["hpi_redacted"] and c["audit"]["ed_course_cut"]


def test_cases_without_requiring_hpi(tables, case_tables, notes):
    cases, _ = build_cases(cohort(tables), case_tables, notes, CaseSettings(require_hpi=False))
    assert [c["stay_id"] for c in cases] == [11, 61]
    assert cases[1]["patient_view"]["hpi"] == "" and cases[1]["reference"]["head_injury_icd"] is False


def test_labels_absent_without_diagnoses_file(tables, case_tables, notes):
    del case_tables["hosp_diagnoses"]
    cases, flow = build_cases(cohort(tables), case_tables, notes, CaseSettings())
    assert cases[0]["reference"]["head_injury_icd"] is None
    assert summarize(cases, flow)["head_injury_icd_positive"] is None


def test_save_and_load(tables, case_tables, notes, tmp_path):
    cases, flow = build_cases(cohort(tables), case_tables, notes, CaseSettings())
    report = save_cases(tmp_path, cases, flow, CaseSettings())
    assert load_cases(tmp_path) == cases
    assert report["cases"] == 1 and report["head_injury_icd_positive"] == 1
    assert report["removed_sentences_by_rule"] == {"imaging": 1}


def test_read_discharge_notes_in_chunks(tmp_path):
    import pandas as pd
    from triagesim.cases.build import read_discharge_notes
    pd.DataFrame({"hadm_id": [101, 101, 202, 303], "note_seq": [2, 1, 1, 1],
                  "text": ["second", "first", "other", "x"]}).to_csv(tmp_path / "d.csv.gz", index=False)
    seen = []
    notes = read_discharge_notes(tmp_path / "d.csv.gz", {101, 303}, progress=seen.append, chunksize=2)
    assert notes == {101: "first", 303: "x"} and seen == [2, 4]
