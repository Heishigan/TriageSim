"""A demo model: plausible canned answers, so the app can be tried without a GPU.

It is NOT a language model and its results mean nothing. Choose it with
``source: demo`` in an experiment to see the pipeline and the live view work.
"""
from __future__ import annotations

import hashlib
import json
import random

from .base import ChatResult, Message

PATIENT_LINES = [
    "I slipped in the bathroom this morning and landed on my side.",
    "I think I hit my head on the sink, but I'm not sure.",
    "I take a blood thinner for my heart rhythm.",
    "My hip hurts a lot when I try to stand.",
    "No, I didn't black out. I remember everything.",
    "I've been a bit dizzy since yesterday.",
]
NURSE_QUESTIONS = [
    "Did you hit your head or lose consciousness?",
    "Do you take any blood thinners?",
    "Where does it hurt the most, and how bad is it from 0 to 10?",
]


class DemoModel:
    def __init__(self, name: str = "demo"):
        self.name = name

    def chat(self, messages: list[Message], *, temperature=None, seed=None, json_schema=None) -> ChatResult:
        rng = random.Random(hashlib.sha256(messages[0].content.encode()).hexdigest())
        props = (json_schema or {}).get("properties", {})
        if "action" in props:                                   # nurse turn
            asked = sum(1 for m in messages if m.role == "assistant")
            if asked <= len(NURSE_QUESTIONS):
                text = json.dumps({"action": "ask", "message": NURSE_QUESTIONS[asked - 1], "esi": None})
            else:
                text = json.dumps({"action": "decide", "esi": rng.choice([2, 2, 3, 3, 4]),
                                   "message": "Fall with possible head strike; I'll prioritise imaging."})
        elif "changed" in props:                                # self-review
            text = json.dumps({"esi": rng.choice([2, 3]), "changed": False, "reasoning": "Demo review."})
        elif "history_taking" in props:                         # evaluator
            text = json.dumps({"history_taking": rng.randint(5, 9), "risk_identification": rng.randint(4, 9),
                               "decision": rng.randint(4, 9), "feedback": "Demo feedback (not a real evaluation)."})
        elif "answer" in props:
            text = json.dumps({"answer": rng.choice("BCD"), "reasoning": "Demo answer."})
        elif "esi" in props:
            text = json.dumps({"esi": rng.choice([2, 3, 4]), "reasoning": "Demo decision."})
        else:                                                   # patient
            n = sum(1 for m in messages if m.role == "assistant")
            text = PATIENT_LINES[(n + rng.randint(0, 5)) % len(PATIENT_LINES)]
        return ChatResult(content=text, model=self.name, prompt_tokens=50, completion_tokens=20, seconds=0.2)


def demo_embed(texts: list[str]) -> list[list[float]]:
    """A crude bag-of-words embedding for demos and tests."""
    vocab = ["head", "fall", "blood", "thinner", "pain", "hip", "dizzy", "medication", "warfarin", "apixaban"]
    return [[t.lower().count(w) + 0.01 for w in vocab] for t in texts]
