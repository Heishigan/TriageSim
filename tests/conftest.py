"""A tiny invented dataset shaped like MIMIC-IV-ED. No real patient data.

Subjects:
  1  F, 70, admitted, fall (ICD-10), two visits     -> kept once (first visit)
  2  M, 50, admitted, fall                           -> too young
  3  F, 80, not admitted, fall                       -> not admitted
  4  M, 80, admitted, head injury code, no fall      -> no fall code
  5  F, 80, admitted, fall, no acuity                -> no ESI
  6  M, 90, admitted, fall (ICD-9 with dot)          -> kept
"""
import pandas as pd
import pytest


@pytest.fixture
def tables():
    return {
        "patients": pd.DataFrame({
            "subject_id": [1, 2, 3, 4, 5, 6],
            "gender": ["F", "M", "F", "M", "F", "M"],
            "anchor_age": [70, 50, 80, 80, 80, 88],
            "anchor_year": [2150] * 6,
        }),
        "edstays": pd.DataFrame({
            "subject_id": [1, 1, 2, 3, 4, 5, 6],
            "hadm_id": [101, 102, 201, None, 401, 501, 601],
            "stay_id": [11, 12, 21, 31, 41, 51, 61],
            "intime": ["2150-03-01", "2151-03-01", "2150-01-01", "2150-01-01",
                       "2150-01-01", "2150-01-01", "2152-06-01"],
            "disposition": ["ADMITTED", "ADMITTED", "ADMITTED", "TRANSFER",
                            "ADMITTED", "ADMITTED", "ADMITTED"],
        }),
        "triage": pd.DataFrame({
            "stay_id": [11, 12, 21, 31, 41, 51, 61],
            "acuity": [2, 3, 2, 2, 2, None, 1],
            "chiefcomplaint": ["Fall"] * 7,
        }),
        "ed_diagnosis": pd.DataFrame({
            "stay_id": [11, 11, 12, 21, 31, 41, 51, 61],
            "seq_num": [1, 2, 1, 1, 1, 1, 1, 1],
            "icd_code": ["W19XXXA", "S0990XA", "W010XXA", "W19XXXA", "W19XXXA",
                         "S0600XA", "W19XXXA", "E888.9"],
            "icd_version": [10, 10, 10, 10, 10, 10, 10, 9],
            "icd_title": ["Fall", "Head injury", "Fall on ice", "Fall", "Fall", "Concussion",
                          "Fall", "Fall NOS"],
        }),
    }


# Invented discharge summaries in MIMIC-IV-Note style (no real text).
NOTE_11 = """Name: ___  Unit No: ___
Chief Complaint:
fall

History of Present Illness:
Ms. ___ is a 70 year old woman with atrial fibrillation on apixaban who tripped over a rug at home
this morning and struck her forehead on a table. She denies loss of consciousness. She has a mild
headache. CT head showed a small subdural hematoma. In the ED, initial vitals were 98.6 80 140/80.
She was given ondansetron and admitted to neurosurgery.

Past Medical History:
Atrial fibrillation, hypertension

Social History:
Lives alone, walks with a cane.

Allergies:
Penicillins

Brief Hospital Course:
Ms. ___ was admitted with a traumatic subdural hematoma.
"""

NOTE_61 = """Chief Complaint:
fall
Brief Hospital Course:
Admitted after fall.
"""


@pytest.fixture
def case_tables(tables):
    """Tables used by the case builder, for the same invented stays."""
    return {
        "triage_vitals": pd.DataFrame({
            "stay_id": [11, 12, 21, 31, 41, 51, 61],
            "temperature": [98.6] * 7, "heartrate": [80, 90, 70, 75, 88, 92, 110],
            "resprate": [16] * 7, "o2sat": [97] * 7, "sbp": [140] * 7, "dbp": [80] * 7,
            "pain": ["4", "2", "0", "3", "5", "1", "8"]}),
        "edstays_arrival": pd.DataFrame({
            "stay_id": [11, 12, 21, 31, 41, 51, 61],
            "arrival_transport": ["AMBULANCE", "WALK IN", "WALK IN", "AMBULANCE", "WALK IN",
                                  "WALK IN", "AMBULANCE"]}),
        "medrecon": pd.DataFrame({"stay_id": [11, 11, 11, 61], "name": ["Apixaban", "Lisinopril",
                                                                        "Apixaban", "Aspirin"]}),
        "hosp_diagnoses": pd.DataFrame({"hadm_id": [101, 101, 601], "icd_code": ["S065X0A", "I10", "W19XXXA"],
                                        "icd_version": [10, 10, 10]}),
    }


@pytest.fixture
def notes():
    return {101: NOTE_11, 601: NOTE_61}


@pytest.fixture
def data_dir(tmp_path, tables):
    """The same tables written as .csv.gz files in the required layout."""
    layout = {"patients": "hosp/patients.csv.gz",
              "edstays": "ed/edstays.csv.gz",
              "triage": "ed/triage.csv.gz",
              "ed_diagnosis": "ed/diagnosis.csv.gz"}
    for key, rel in layout.items():
        path = tmp_path / "data" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tables[key].to_csv(path, index=False)
    return tmp_path / "data"


@pytest.fixture
def app_dirs(data_dir, tmp_path, monkeypatch):
    """Point the app's fixed folders at the test data and a temporary outputs folder."""
    monkeypatch.setenv("TRIAGESIM_DATA_DIR", str(data_dir))
    monkeypatch.setenv("TRIAGESIM_OUTPUT_DIR", str(tmp_path / "outputs"))
    return data_dir, tmp_path / "outputs"
