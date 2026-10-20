"""The agents: a patient (free text, or answering only from retrieved record passages)
and a structured caller used for the nurse, self-review and evaluator."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

from ..llm.base import ChatModel, ChatResult, Message
from .config import Agent, ModelSettings, Patient
from .fields import render
from .protocol import ProtocolError

Embedder = Callable[[list[str]], list[list[float]]]


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    max_prompt_tokens: int = 0       # largest single prompt
    context_full: int = 0            # calls that filled the context window (prompt likely cut off)
    completion_tokens: int = 0
    seconds: float = 0.0
    format_retries: int = 0
    format_failures: int = 0

    def add(self, r: ChatResult, num_ctx: int | None = None) -> None:
        self.calls += 1
        self.max_prompt_tokens = max(self.max_prompt_tokens, r.prompt_tokens)
        if num_ctx and r.prompt_tokens + r.completion_tokens >= 0.97 * num_ctx:
            self.context_full += 1
        self.prompt_tokens += r.prompt_tokens
        self.completion_tokens += r.completion_tokens
        self.seconds += r.seconds


def choose_persona(patient: Patient, case_id: str, seed: int) -> str:
    """The persona name for a case: fixed, or drawn reproducibly per case."""
    if patient.persona != "random":
        return patient.persona
    options = sorted(k for k in patient.personas if k != "neutral")
    return random.Random(f"{seed}:{case_id}").choice(options)


def ask_structured(model: ChatModel, settings: ModelSettings, messages: list[Message], schema: dict,
                   parse: Callable[[str], dict], usage: Usage) -> tuple[dict | None, str]:
    """Call a model for a structured answer; one retry with the error explained.

    Returns (parsed or None if it failed twice, raw text of the last reply).
    """
    result = model.chat(messages, temperature=settings.temperature, seed=settings.seed, json_schema=schema,
                        max_tokens=settings.max_tokens, num_ctx=settings.num_ctx)
    usage.add(result, settings.num_ctx)
    try:
        return parse(result.content), result.content
    except ProtocolError as exc:
        usage.format_retries += 1
        retry = messages + [Message("assistant", result.content),
                            Message("user", f"That reply was not valid ({exc}). Reply again in the required JSON format.")]
        result = model.chat(retry, temperature=settings.temperature, seed=settings.seed, json_schema=schema,
                            max_tokens=settings.max_tokens, num_ctx=settings.num_ctx)
        usage.add(result, settings.num_ctx)
        try:
            return parse(result.content), result.content
        except ProtocolError:
            usage.format_failures += 1
            return None, result.content


class LLMPatient:
    """Answers the nurse in character, from what the patient is allowed to know."""

    def __init__(self, config: Patient, model: ChatModel, values: dict[str, str], usage: Usage):
        self.config, self.model, self.usage = config, model, usage
        system = render(config.system_prompt, values, set(config.sees))
        self.history = [Message("system", system)]

    def reply(self, nurse_message: str) -> str:
        self.history.append(Message("user", nurse_message))
        r = self.model.chat(self.history, temperature=self.config.model.temperature, seed=self.config.model.seed,
                            max_tokens=self.config.model.max_tokens, num_ctx=self.config.model.num_ctx)
        self.usage.add(r, self.config.model.num_ctx)
        self.history.append(Message("assistant", r.content))
        return r.content


def chunk_text(text: str, size: int) -> list[str]:
    """Split text into pieces of about ``size`` characters at sentence or word boundaries."""
    chunks, current = [], ""
    for sentence in text.replace("\n", " ").split(". "):
        sentence = sentence.strip()
        if not sentence:
            continue
        piece = sentence if sentence.endswith(".") else sentence + "."
        if current and len(current) + len(piece) + 1 > size:
            chunks.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        chunks.append(current)
    return chunks


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


RETRIEVAL_PROMPT = """You are a patient talking to a triage nurse. Answer the nurse's question in one or two
sentences, in the first person, using ONLY the facts below. If the facts do not answer the
question, say you are not sure. Do not add anything that is not in the facts.

Facts:
{facts}

Nurse: {question}
Patient:"""


@dataclass
class RetrievalPatient:
    """Answers only from the most relevant passages of the patient's record."""
    config: Patient
    model: ChatModel
    values: dict[str, str]
    usage: Usage
    embed: Embedder
    chunks: list[str] = field(default_factory=list)
    vectors: list[list[float]] = field(default_factory=list)
    last_retrieved: list[str] = field(default_factory=list)

    def __post_init__(self):
        record = " ".join(f"{name.replace('_', ' ').capitalize()}: {self.values[name]}."
                          for name in ("hpi", "past_medical_history", "medications", "allergies", "social_history")
                          if name in self.config.sees)
        self.chunks = chunk_text(record, self.config.retrieval_chunk_chars) or ["No information available."]
        self.vectors = self.embed(self.chunks)

    def reply(self, nurse_message: str) -> str:
        q = self.embed([nurse_message])[0]
        ranked = sorted(range(len(self.chunks)), key=lambda i: _cosine(q, self.vectors[i]), reverse=True)
        self.last_retrieved = [self.chunks[i] for i in ranked[: self.config.retrieval_top_k]]
        prompt = RETRIEVAL_PROMPT.format(facts="\n".join(self.last_retrieved), question=nurse_message)
        r = self.model.chat([Message("user", prompt)], temperature=self.config.model.temperature,
                            seed=self.config.model.seed, max_tokens=self.config.model.max_tokens,
                            num_ctx=self.config.model.num_ctx)
        self.usage.add(r, self.config.model.num_ctx)
        return r.content


def system_message(agent: Agent, values: dict[str, str], instructions: str) -> Message:
    return Message("system", render(agent.system_prompt, values, set(agent.sees)) + instructions)
