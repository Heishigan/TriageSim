"""Invented MIMIC-shaped data (no real patients), for demos and browser tests.

`triagesim ui --demo` writes it to demo/data/ and keeps demo outputs in demo/outputs/,
so a demo never touches the real data/ and outputs/ folders.
"""
from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

HPI = ("Invented patient who slipped at home and fell. She hit her head on a table and takes a blood "
       "thinner. She denies loss of consciousness. CT head showed a small bleed. In the ED, initial "
       "vitals were stable.")


def make_demo_data(folder: Path, patients: int = 60, seed: int = 0) -> None:
    rng = random.Random(seed)
    for sub in ("hosp", "ed", "note"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    subj = list(range(1, patients + 1))
    pd.DataFrame({"subject_id": subj, "gender": [rng.choice("FM") for _ in subj],
                  "anchor_age": [rng.randint(55, 95) for _ in subj], "anchor_year": 2150}
                 ).to_csv(folder / "hosp/patients.csv.gz", index=False)
    stays = pd.DataFrame({
        "subject_id": subj, "stay_id": [1000 + s for s in subj],
        "hadm_id": [2000 + s if rng.random() < .8 else None for s in subj],
        "intime": [f"2150-0{rng.randint(1, 9)}-1{rng.randint(0, 9)} 10:00:00" for _ in subj],
        "disposition": "ADMITTED", "arrival_transport": [rng.choice(["AMBULANCE", "WALK IN"]) for _ in subj]})
    stays.to_csv(folder / "ed/edstays.csv.gz", index=False)
    pd.DataFrame({"stay_id": stays.stay_id, "acuity": [rng.choice([1, 2, 2, 3, 3, 4]) for _ in subj],
                  "chiefcomplaint": "S/P FALL", "temperature": 98.1,
                  "heartrate": [rng.randint(60, 110) for _ in subj], "resprate": 16, "o2sat": 97,
                  "sbp": [rng.randint(100, 170) for _ in subj], "dbp": 80,
                  "pain": [str(rng.randint(0, 9)) for _ in subj]}).to_csv(folder / "ed/triage.csv.gz", index=False)
    pd.DataFrame({"stay_id": stays.stay_id, "seq_num": 1,
                  "icd_code": [rng.choice(["W19XXXA", "W010XXA", "S0600XA", "R55"]) for _ in subj],
                  "icd_version": 10, "icd_title": "invented"}).to_csv(folder / "ed/diagnosis.csv.gz", index=False)
    pd.DataFrame({"stay_id": stays.stay_id,
                  "name": [rng.choice(["Apixaban", "Warfarin", "Lisinopril", "Metoprolol"]) for _ in subj]}
                 ).to_csv(folder / "ed/medrecon.csv.gz", index=False)
    admitted = stays.hadm_id.dropna().astype(int)
    pd.DataFrame({"hadm_id": admitted, "icd_code": [rng.choice(["S065X0A", "I10", "W19XXXA"]) for _ in admitted],
                  "icd_version": 10}).to_csv(folder / "hosp/diagnoses_icd.csv.gz", index=False)
    note = ("Chief Complaint:\nfall\n\nHistory of Present Illness:\n" + HPI +
            "\n\nPast Medical History:\nAtrial fibrillation\n\nAllergies:\nNone\n")
    pd.DataFrame({"hadm_id": admitted, "note_seq": 1, "text": note}).to_csv(folder / "note/discharge.csv.gz", index=False)
