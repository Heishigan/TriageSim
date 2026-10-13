"""Case fields an agent may read, and how they are rendered into prompts."""
from __future__ import annotations

import string

from ..cases.build import VITALS

# field -> (where it comes from, short description)
FIELDS = {
    "age": ("nurse_view", "Age at the ED visit"),
    "sex": ("nurse_view", "Sex (F/M)"),
    "chief_complaint": ("nurse_view", "Chief complaint recorded at triage"),
    "arrival_transport": ("nurse_view", "How the patient arrived (ambulance, walk-in, ...)"),
    "vitals": ("nurse_view", "Triage vital signs"),
    "hpi": ("patient_view", "History of present illness (redacted)"),
    "past_medical_history": ("patient_view", "Past medical history"),
    "social_history": ("patient_view", "Social history"),
    "allergies": ("patient_view", "Allergies"),
    "medications": ("patient_view", "Home medications"),
    "persona": ("experiment", "Behaviour assigned to the patient"),
    "esi": ("reference", "Triage nurse's ESI (ground truth)"),
    "disposition": ("reference", "ED disposition"),
    "head_injury": ("reference", "Head-injury label (ICD)"),
    "transcript": ("run", "The full conversation"),
    "decision": ("run", "The ESI the nurse agent assigned"),
}
REFERENCE_FIELDS = {k for k, (src, _) in FIELDS.items() if src in ("reference", "run")}


def template_fields(template: str) -> set[str]:
    """Names used as {placeholders} in a prompt template."""
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def case_values(case: dict, persona: str = "", extra: dict | None = None) -> dict[str, str]:
    """Every field rendered as text for one case."""
    nv, pv, ref = case["nurse_view"], case["patient_view"], case["reference"]
    vitals = ", ".join(f"{label}: {nv['vitals'][k]}" for k, label in VITALS.items()
                       if nv["vitals"].get(k) is not None) or "not recorded"
    values = {
        "age": str(nv["age"]), "sex": {"F": "female", "M": "male"}.get(nv["sex"], str(nv["sex"])),
        "chief_complaint": nv.get("chief_complaint") or "not recorded",
        "arrival_transport": (nv.get("arrival_transport") or "unknown").lower(),
        "vitals": vitals,
        "hpi": pv.get("hpi") or "not available",
        "past_medical_history": pv.get("past_medical_history") or "not available",
        "social_history": pv.get("social_history") or "not available",
        "allergies": pv.get("allergies") or "not available",
        "medications": ", ".join(pv.get("medications") or []) or "none recorded",
        "persona": persona,
        "esi": str(ref.get("esi")), "disposition": str(ref.get("disposition")),
        "head_injury": {True: "yes", False: "no", None: "unknown"}[ref.get("head_injury_icd")],
    }
    values.update(extra or {})
    return values


def render(template: str, values: dict[str, str], allowed: set[str]) -> str:
    """Fill a template, using only the fields this agent is allowed to see."""
    return template.format(**{k: v for k, v in values.items() if k in allowed})
