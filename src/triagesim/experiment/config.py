"""Experiment configuration (one YAML file per experiment), validated before a run."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .fields import FIELDS, REFERENCE_FIELDS, template_fields


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")   # a typo in the YAML is an error, not ignored


class ModelSettings(Strict):
    name: str = Field(description="Model name in Ollama, e.g. qwen2.5:32b")
    source: Literal["ollama", "huggingface", "demo", "fake"] = "ollama"
    hf_repo: str | None = Field(None, description="Hugging Face repo with a GGUF file")
    hf_file: str | None = Field(None, description="GGUF file name in that repo")
    temperature: float | None = Field(None, ge=0, le=2)
    seed: int | None = None
    max_tokens: int | None = Field(
        8192, ge=64, description="Most tokens one reply may have, reasoning included. Stops a model that "
        "keeps writing; a cut-off reply counts as a format failure. Empty = no limit")
    num_ctx: int | None = Field(
        None, ge=512, description="Context window in tokens (prompt + reply). Empty = Ollama's default, which "
        "depends on the GPU (32,768 on the cluster's L40S, often 2,048-4,096 on a PC); a prompt longer than the "
        "window is cut off silently, so set it for long prompts")

    @model_validator(mode="after")
    def _local_only(self):
        if "cloud" in self.name.lower().replace(":", "-").split("-"):
            raise ValueError(f"'{self.name}' is a cloud model: it runs on Ollama's servers, so case data would "
                             "leave this computer. MIMIC data must stay local; choose a local model.")
        return self

    @model_validator(mode="after")
    def _hf(self):
        if self.source == "huggingface" and not (self.hf_repo and self.hf_file):
            raise ValueError("A Hugging Face model needs hf_repo and hf_file.")
        return self


class Agent(Strict):
    model: ModelSettings
    sees: list[str] = Field(description="Case fields this agent may read")
    system_prompt: str

    @model_validator(mode="after")
    def _visibility(self):
        unknown = set(self.sees) - set(FIELDS)
        if unknown:
            raise ValueError(f"Unknown field(s) in 'sees': {sorted(unknown)}")
        used = template_fields(self.system_prompt)
        if "similar_cases" in self.sees and type(self).__name__ != "Nurse":
            raise ValueError("Only the nurse can see similar cases.")
        hidden = used - set(self.sees)
        if hidden:
            raise ValueError(f"The prompt uses {sorted(hidden)} but the agent may not see them. "
                             "Add them to 'sees' or remove them from the prompt.")
        return self


class Patient(Agent):
    mode: Literal["llm", "retrieval"] = "llm"
    persona: str = Field("neutral", description="A persona name, or 'random' to draw one per case")
    personas: dict[str, str] = Field(default_factory=dict)
    retrieval_embedding_model: str = "nomic-embed-text"
    retrieval_chunk_chars: int = Field(300, ge=50)
    retrieval_top_k: int = Field(3, ge=1)

    @model_validator(mode="after")
    def _persona(self):
        if self.persona != "random" and self.persona not in self.personas:
            raise ValueError(f"Persona '{self.persona}' is not defined in 'personas'.")
        if REFERENCE_FIELDS & set(self.sees):
            raise ValueError("The patient may not see reference answers.")
        return self


class SimilarCaseSettings(Strict):
    """Retrieved similar past patients for the nurse (Lee et al. 2025, KATE)."""
    k: int = Field(40, ge=1, le=200, description="Examples shown per patient")
    candidates_per_example: int = Field(3, ge=1, description="Stage 1 keeps k x this by complaint similarity")
    embedding_model: str = "nomic-embed-text"


class Nurse(Agent):
    mode: Literal["interview", "chart_review", "multiple_choice"] = "interview"
    opening_message: str = "Hello, I'm the triage nurse. What brings you in today?"
    max_turns: int = Field(12, ge=1, le=50)
    similar_cases: SimilarCaseSettings | None = None

    @model_validator(mode="after")
    def _no_answers(self):
        if REFERENCE_FIELDS & set(self.sees):
            raise ValueError("The nurse may not see reference answers.")
        if ("similar_cases" in self.sees) != (self.similar_cases is not None):
            raise ValueError("'similar_cases' in 'sees' and the similar_cases settings go together.")
        if self.similar_cases is not None and self.mode != "chart_review":
            raise ValueError("Similar cases are only available for chart review.")
        return self


class Evaluator(Agent):
    enabled: bool = True


class Sampling(Strict):
    cases: int | None = Field(None, ge=1, description="Number of cases; empty = all")
    order: Literal["random", "first", "stratified"] = Field(
        "random", description="random: seeded random sample; first: cases in file order; stratified: "
        "seeded random sample with the same ESI distribution as the cohort")
    seed: int = 42
    stratify_head_injury: bool = Field(
        False, description="With 'stratified': also keep the share of head-injury cases (ICD label) "
        "within each ESI level, as in the case pool")


class ExperimentConfig(Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    description: str = ""
    cohort: str = Field(description="Folder name of a saved cohort with case files")
    ollama_url: str = "http://127.0.0.1:11434"
    sampling: Sampling = Sampling()
    nurse: Nurse
    patient: Patient | None = None
    evaluator: Evaluator | None = None

    @model_validator(mode="after")
    def _needs_patient(self):
        if self.nurse.mode == "interview" and self.patient is None:
            raise ValueError("An interview needs a patient agent.")
        return self

    def models(self) -> list[ModelSettings]:
        agents = [self.nurse, self.patient, self.evaluator if self.evaluator and self.evaluator.enabled else None]
        return [a.model for a in agents if a is not None]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ExperimentConfig":
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})

    def to_yaml(self, path: str | Path) -> None:
        Path(path).write_text(yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
                              encoding="utf-8")
