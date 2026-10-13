"""A plain-language summary of a run's metrics, written by a model."""
from __future__ import annotations

import json

from ..llm.base import ChatModel, Message

SUMMARY_PROMPT = """You are helping a clinical researcher read the results of a simulated emergency
triage experiment. A language-model "nurse" assigned Emergency Severity Index (ESI) levels;
they are compared with the real triage nurse's ESI. Under-triage means less urgent than the
real nurse (a safety concern); over-triage means more urgent.

Write a short summary (at most 150 words) for the researcher: the main findings, anything
concerning, and one or two caveats (sample size, wide confidence intervals, undecided cases).
Use only the numbers below; do not invent any. Plain text, no headings."""


def summarize_metrics(model: ChatModel, experiment: str, metrics: dict) -> str:
    slim = {k: v for k, v in metrics.items() if k != "confusion"}
    messages = [Message("system", SUMMARY_PROMPT),
                Message("user", f"Experiment: {experiment}\nMetrics (JSON):\n{json.dumps(slim, indent=1)}")]
    return model.chat(messages, temperature=0.2).content
