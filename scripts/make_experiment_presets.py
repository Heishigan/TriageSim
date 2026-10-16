"""Write the experiment presets in configs/experiments/. Run once after editing the texts below."""
from pathlib import Path

import yaml

# The ESI decision points (Emergency Severity Index Handbook, 5th ed., ENA 2023), used in every
# nurse prompt so the conditions differ only in how the information is obtained. A stepwise
# decision-tree prompt clearly beat open prompts in Benning et al. (medRxiv 2026).
ESI_GUIDE = """Decide the Emergency Severity Index (ESI) level step by step, as in the ESI algorithm:
A. Does the patient need an immediate life-saving intervention (airway or breathing support,
   emergency medication, or haemodynamic intervention such as fluid resuscitation or blood)?
   If yes: ESI 1.
B. Is this a high-risk situation, or is the patient newly confused, lethargic or disoriented,
   or in severe pain or distress? If yes: ESI 2.
C. Otherwise, how many different types of resources will the patient likely need? Resources
   are: laboratory tests, ECG or X-rays, CT/MRI/ultrasound, IV fluids, IV/IM/nebulised
   medication, specialty consultation, a simple procedure (counts as one) or a complex procedure
   (counts as two). History and examination, point-of-care tests, oral medication, tetanus
   shots, simple wound care, splints and slings do not count.
   None: ESI 5. One: ESI 4. Two or more: go to D.
D. Are the vital signs in the danger zone (heart rate above 100, respiratory rate above 20,
   oxygen saturation below 92%)? If yes, consider ESI 2; otherwise ESI 3."""

NURSE_INTERVIEW = f"""You are an experienced emergency department triage nurse. A patient has just arrived.
Interview them and decide their Emergency Severity Index (ESI) level.

Before the interview you know:
- A {{age}}-year-old {{sex}} who arrived by {{arrival_transport}}.
- Chief complaint: {{chief_complaint}}
- Triage vital signs: {{vitals}}

How to interview:
- Ask one short question at a time and wait for the answer.
- Find out what happened and how, whether they hit their head or lost consciousness,
  whether they take blood thinners, where it hurts and how much, and any new symptoms.
- Use only what the patient tells you and the information above. Do not invent facts.
- Decide as soon as you have enough information.

{ESI_GUIDE}"""

NURSE_CHART = f"""You are an experienced emergency department triage nurse reviewing a patient's chart.
Assign the Emergency Severity Index (ESI) level.

Patient: {{age}}-year-old {{sex}}, arrived by {{arrival_transport}}.
Chief complaint: {{chief_complaint}}
Triage vital signs: {{vitals}}
History of present illness: {{hpi}}
Past medical history: {{past_medical_history}}
Home medications: {{medications}}

{ESI_GUIDE}"""

NURSE_MCQ = f"""Answer this board-style question.

A {{age}}-year-old {{sex}} arrives at the emergency department by {{arrival_transport}}.
Chief complaint: {{chief_complaint}}. Triage vital signs: {{vitals}}.
History: {{hpi}}
Past medical history: {{past_medical_history}}. Home medications: {{medications}}.

What is the most appropriate Emergency Severity Index (ESI) level?
A) ESI 1   B) ESI 2   C) ESI 3   D) ESI 4   E) ESI 5

{ESI_GUIDE}"""

PATIENT = """You are role-playing a patient who has just arrived at an emergency department and is
talking to the triage nurse. Stay in character. Never say you are an AI.

About you: a {age}-year-old {sex}. You came in because of: {chief_complaint}.

What happened, and your background, from your medical record. Tell it in your own words
when asked; never read it out or list it all at once:
{hpi}

Past medical history: {past_medical_history}
Medications you take: {medications}
Allergies: {allergies}
Your living situation: {social_history}

Where the record shows ___, a detail was removed for privacy. Do not mention it or make it up.
If the nurse asks about something not covered here, answer as a typical patient would,
without inventing serious symptoms.

How you behave: {persona}

Reply with spoken words only (no actions or stage directions), in one to three sentences."""

PERSONAS = {
    "neutral": "Open and cooperative. You answer every question truthfully and fully.",
    "cooperative": "Cooperative but tired. You answer directly and honestly but do not volunteer "
                   "details you are not asked about.",
    "stoic": "Stoic and proud. You downplay pain and give very short answers. You only mention "
             "hitting your head or blacking out if the nurse asks about it directly.",
    "anxious": "Anxious. You keep returning to a minor scrape or bruise and tend to forget more "
               "serious symptoms unless the nurse asks about them.",
    "confused": "Mildly confused. You are unsure of the exact sequence of events, sometimes "
                "repeat yourself and need gentle prompting.",
}

EVALUATOR = """You are an attending emergency physician reviewing a triage interview done by a nurse.
You know the facts the nurse did not see.

Case facts: {age}-year-old {sex}. Chief complaint: {chief_complaint}.
History: {hpi}
Home medications: {medications}
Reference ESI (assigned by the real triage nurse): {esi}
Head injury on the hospital diagnoses: {head_injury}

The nurse agent assigned: ESI {decision}

Transcript:
{transcript}

Score the nurse from 0 to 10 on: history taking (did they ask what mattered, such as head
strike and blood thinners?), risk identification (did they recognise dangerous features?)
and decision (is the ESI appropriate?). Give short, specific feedback."""

QWEN, LLAMA = "qwen2.5:32b", "llama3.1:8b"
EVERYTHING = ["age", "sex", "chief_complaint", "arrival_transport", "vitals", "hpi",
              "past_medical_history", "social_history", "allergies", "medications"]


def nurse(mode, prompt, sees):
    return {"mode": mode, "model": {"name": QWEN, "temperature": 0.0, "seed": 42},
            "sees": sees, "system_prompt": prompt,
            "opening_message": "Hello, I'm the triage nurse. What brings you in today?",
            "max_turns": 12}


def patient(persona="neutral", mode="llm"):
    return {"mode": mode, "model": {"name": LLAMA, "temperature": 0.7, "seed": 42},
            "sees": ["age", "sex", "chief_complaint", "hpi", "past_medical_history", "social_history",
                     "allergies", "medications", "persona"],
            "system_prompt": PATIENT, "persona": persona, "personas": PERSONAS}


EVAL = {"enabled": True, "model": {"name": QWEN, "temperature": 0.0, "seed": 42},
        "sees": ["age", "sex", "chief_complaint", "hpi", "medications", "esi", "head_injury",
                 "decision", "transcript"], "system_prompt": EVALUATOR}
NURSE_SEES = ["age", "sex", "chief_complaint", "arrival_transport", "vitals"]

PRESETS = {
    # One interview preset: patient type (language model or retrieval) and persona (fixed or
    # random per case) are options in the form, not separate presets.
    "interview": ("Nurse interviews a simulated patient. Choose the patient type and persona below.",
                  {"nurse": nurse("interview", NURSE_INTERVIEW, NURSE_SEES), "patient": patient(), "evaluator": EVAL}),
    "chart_review": ("Nurse reads the chart and decides, without talking to the patient.",
                     {"nurse": nurse("chart_review", NURSE_CHART,
                                     ["age", "sex", "chief_complaint", "arrival_transport", "vitals", "hpi",
                                      "past_medical_history", "medications"])}),
    "multiple_choice": ("The same information as a board-style multiple-choice question.",
                        {"nurse": nurse("multiple_choice", NURSE_MCQ,
                                        ["age", "sex", "chief_complaint", "arrival_transport", "vitals", "hpi",
                                         "past_medical_history", "medications"])}),
}

out = Path(__file__).resolve().parents[1] / "configs" / "experiments"
out.mkdir(parents=True, exist_ok=True)


class Literal(str):
    pass


yaml.SafeDumper.add_representer(
    Literal, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style="|"))


def literal(obj):
    if isinstance(obj, dict):
        return {k: literal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [literal(v) for v in obj]
    if isinstance(obj, str) and "\n" in obj:
        return Literal(obj)
    return obj


for name, (description, parts) in PRESETS.items():
    config = {"name": name, "description": description, "cohort": "elderly_falls",
              "ollama_url": "http://127.0.0.1:11434",
              "sampling": {"cases": 20, "order": "stratified", "seed": 42, "stratify_head_injury": True}, **parts}
    (out / f"{name}.yaml").write_text(yaml.safe_dump(literal(config), sort_keys=False, allow_unicode=True,
                                                     width=100), encoding="utf-8")
    print("wrote", name)


# ---- Benchmark: same cases, prompts, patient and evaluator; only the nurse's model changes.
BENCHMARK_NURSES = {
    "qwen25-32b": "qwen2.5:32b",    # anchor: the thesis nurse model
    "gemma3-27b": "gemma3:27b",     # general model ...
    "medgemma-27b": "medgemma:27b", # ... and its medical fine-tune (same base): isolates medical training
}
# Evaluator from another model family than every nurse, so it does not grade its own kind.
BENCHMARK_EVALUATOR = "gpt-oss:20b"
bench = out / "benchmark"
bench.mkdir(exist_ok=True)
for preset in ("chart_review", "interview"):
    description, parts = PRESETS[preset]
    for short, model in BENCHMARK_NURSES.items():
        nurse_part = {**parts["nurse"], "model": {"name": model, "temperature": 0.0, "seed": 42}}
        config = {"name": f"bench_{preset}_{short}",
                  "description": f"Benchmark: {description} Nurse model {model}.",
                  "cohort": "elderly_falls", "ollama_url": "http://127.0.0.1:11434",
                  "sampling": {"cases": 100, "order": "random", "seed": 42},
                  **parts, "nurse": nurse_part}
        if "evaluator" in config:
            config["evaluator"] = {**config["evaluator"],
                                   "model": {"name": BENCHMARK_EVALUATOR, "temperature": 0.0, "seed": 42}}
        (bench / f"{preset}_{short}.yaml").write_text(
            yaml.safe_dump(literal(config), sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
        print("wrote benchmark", preset, short)
