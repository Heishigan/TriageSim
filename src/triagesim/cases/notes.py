"""Split MIMIC-IV discharge notes into sections and redact the HPI.

A discharge summary is written after the hospital stay, so its History of Present
Illness (HPI) often contains things a patient could not know at triage: the ED
course, imaging results, lab values. ``redact_hpi`` removes them with transparent
rules and reports what kind of content was removed, so every change can be reviewed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Section headers as they appear in MIMIC-IV discharge summaries (start of a line, colon).
SECTION_HEADERS = {
    "chief_complaint": ["Chief Complaint"],
    "hpi": ["History of Present Illness", "HPI"],
    "past_medical_history": ["Past Medical History", "PMH", "Past Medical/Surgical History"],
    "social_history": ["Social History"],
    "family_history": ["Family History"],
    "allergies": ["Allergies"],
    "medications_on_admission": ["Medications on Admission", "Home Medications"],
    "physical_exam": ["Physical Exam", "Admission Physical Exam"],
    "pertinent_results": ["Pertinent Results"],
    "hospital_course": ["Brief Hospital Course", "Hospital Course"],
    "discharge_medications": ["Discharge Medications"],
    "discharge_diagnosis": ["Discharge Diagnosis", "Discharge Diagnoses"],
    "procedures": ["Major Surgical or Invasive Procedure"],
    "review_of_systems": ["Review of Systems", "ROS"],
}
_HEADER_TO_KEY = {h.lower(): k for k, hs in SECTION_HEADERS.items() for h in hs}
_HEADER_RE = re.compile(
    r"^[ \t]*(" + "|".join(re.escape(h) for h in sorted(_HEADER_TO_KEY, key=len, reverse=True)) + r")[ \t]*:",
    re.IGNORECASE | re.MULTILINE,
)


def split_sections(text: str) -> dict[str, str]:
    """Map section key -> section text. The first occurrence of each section wins."""
    if not isinstance(text, str):
        return {}
    matches = list(_HEADER_RE.finditer(text))
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        key = _HEADER_TO_KEY[m.group(1).lower()]
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        if key not in sections and body:
            sections[key] = body
    return sections


# ---- HPI redaction -----------------------------------------------------------------

# Everything from the first of these onwards describes events after arrival.
_ED_COURSE = re.compile(
    r"(?:^|(?<=[.\n]))\s*(?:"
    r"in the (?:___ )?(?:ED|E\.D\.|emergency (?:department|room))"
    r"|in (?:the )?ER\b|ED course|on arrival to the (?:ED|floor|emergency)|upon arrival to the (?:ED|floor)"
    r"|on arrival to (?:the )?___|initial vitals?\b|on arrival to the MICU|in the MICU"
    r")",
    re.IGNORECASE,
)

# Sentences mentioning these are removed wherever they appear.
REDACTION_RULES = {
    "imaging": r"\b(CTA?|CT scan|CT head|NCHCT|head CT|MRI|MRA|CXR|x-?rays?|XR|radiograph\w*|imaging|"
               r"ultrasound|FAST exam|scan(?:s|ned)?|echo(?:cardiogram)?|EKG|ECG)\b",
    "test_results": r"\b(showed|shows|revealed|reveals|demonstrated|demonstrates|significant for|"
                    r"notable for|remarkable for|found to have|concerning for|consistent with)\b",
    "labs": r"\b(labs?|INR|PTT|troponin|trop|WBC|Hgb|hemoglobin|hematocrit|Hct|lactate|"
            r"creatinine|Cr|BUN|sodium|potassium|glucose|UA|urinalysis|tox screen|BAL|ETOH level)\b",
    "treatment": r"\b(was given|were given|received|administered|started on|intubated|transfused|"
                 r"admitted to|transferred to|consulted|consult|neurosurgery|trauma surgery|"
                 r"was taken to)\b",
}
_RULES = {k: re.compile(v, re.IGNORECASE) for k, v in REDACTION_RULES.items()}
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z_])|\n\s*\n")


@dataclass
class Redaction:
    text: str                               # what the patient agent may use
    removed: dict[str, int] = field(default_factory=dict)   # rule -> sentences removed
    ed_course_cut: bool = False             # True if an ED-course part was cut off
    original_chars: int = 0

    @property
    def changed(self) -> bool:
        return self.ed_course_cut or bool(self.removed)


def redact_hpi(hpi: str) -> Redaction:
    """Remove the ED course and any sentence about tests, results or treatment."""
    original = hpi or ""
    text = original
    cut = _ED_COURSE.search(text)
    ed_cut = bool(cut)
    if cut:
        text = text[: cut.start()]
    kept, removed = [], {}
    for sentence in _SENTENCE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        hit = next((name for name, rule in _RULES.items() if rule.search(sentence)), None)
        if hit:
            removed[hit] = removed.get(hit, 0) + 1
        else:
            kept.append(sentence)
    clean = re.sub(r"[ \t]+", " ", " ".join(kept)).strip()
    return Redaction(clean, removed, ed_cut, len(original))
