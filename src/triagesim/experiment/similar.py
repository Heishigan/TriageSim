"""Similar past patients for the nurse (the "retrieved similar cases" ablation).

Follows KATE as used for ED triage by Lee et al. (2025): for each patient, retrieve the most
similar earlier patients with the ESI level their triage nurse gave, and show them as examples.
Two stages, as in their Appendix A: keep the k x ``candidates_per_example`` patients whose chief
complaint is most similar (embedding cosine; everyone tied with the last place is kept too, since
identical complaint texts all score the same), then the k of those with the closest vital signs
(z-scored on the pool).

The pool is every case of the cohort that is not in the run's sample and does not belong to a
sampled patient; it is fixed when the run is created (pool.json) and the same for every patient.
Only arrival information and the nurse's ESI of pool patients are shown, never a history.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Callable

from ..cases.build import VITALS
from .fields import case_values

EMBED_BATCH = 32          # complaints per embedding request
EMBED_RETRY_WAITS = (5, 30)


def build_pool(cases: list[dict], sample_ids: list[str]) -> list[dict]:
    """Cohort cases usable as examples: not sampled, not from a sampled patient, with an ESI."""
    sampled = set(sample_ids)
    subjects = {c.get("subject_id") for c in cases if c["case_id"] in sampled}
    return sorted((c for c in cases if c["case_id"] not in sampled and c.get("subject_id") not in subjects
                   and c["reference"].get("esi") is not None), key=lambda c: c["case_id"])


def pool_id(case_ids: list[str]) -> str:
    return hashlib.sha1(",".join(sorted(case_ids)).encode()).hexdigest()[:10]


def save_pool(run_dir: Path, pool: list[dict], sample_ids: list[str]) -> dict:
    ids = [c["case_id"] for c in pool]
    assert not set(ids) & set(sample_ids), "a sampled case is in the example pool"
    info = {"pool_id": pool_id(ids), "cases": len(ids), "case_ids": ids}
    (Path(run_dir) / "pool.json").write_text(json.dumps(info, indent=2))
    return info


def _complaint(case: dict) -> str:
    return (case["nurse_view"].get("chief_complaint") or "").strip().lower() or "not recorded"


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class SimilarCases:
    """Retrieval index over a fixed pool. Complaint embeddings are cached in the run folder, so a
    resumed run retrieves exactly the same examples."""

    def __init__(self, pool: list[dict], queries: list[dict], embed: Callable[[list[str]], list[list[float]]],
                 cache: Path | None = None):
        self.pool = pool
        texts = sorted({_complaint(c) for c in pool + queries})
        vectors: dict[str, list[float]] = {}
        if cache and cache.is_file():
            vectors = json.loads(cache.read_text())
        missing = [t for t in texts if t not in vectors]
        for i in range(0, len(missing), EMBED_BATCH):
            batch = missing[i:i + EMBED_BATCH]
            for t, v in zip(batch, _embed_with_retry(embed, batch)):
                vectors[t] = _norm(v)
        if cache and missing:
            cache.write_text(json.dumps(vectors))
        self.vectors = vectors
        self.stats = {}
        for k in VITALS:   # mean and SD of each vital sign over the pool
            xs = [float(c["nurse_view"]["vitals"][k]) for c in pool if _number(c["nurse_view"]["vitals"].get(k))]
            mean = sum(xs) / len(xs) if xs else 0.0
            sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs)) if xs else 1.0
            self.stats[k] = (mean, sd or 1.0)
        self.pool_z = [self._z(c) for c in pool]
        self._ranked: dict[str, list] = {}

    def _z(self, case: dict) -> list[float]:
        vit = case["nurse_view"]["vitals"]
        return [(float(vit[k]) - m) / s if _number(vit.get(k)) else 0.0 for k, (m, s) in self.stats.items()]

    def retrieve(self, case: dict, k: int, candidates_per_example: int) -> list[dict]:
        key = _complaint(case)
        if key not in self._ranked:   # complaint similarity is the same for every patient with this text
            q = self.vectors[key]
            self._ranked[key] = sorted((-sum(a * b for a, b in zip(q, self.vectors[_complaint(c)])), c["case_id"], i)
                                       for i, c in enumerate(self.pool))
        ranked_sims = [r for r in self._ranked[key] if r[1] != case["case_id"]]
        cut = k * candidates_per_example
        if len(ranked_sims) > cut:   # keep every patient tied with the last place (common complaints tie at 1.0)
            last = ranked_sims[cut - 1][0]
            cut = sum(1 for s, _, _ in ranked_sims if s <= last + 1e-9)
        shortlist = ranked_sims[:cut]
        qz = self._z(case)
        ranked = sorted((sum((a - b) ** 2 for a, b in zip(qz, self.pool_z[i])), cid, i) for _, cid, i in shortlist)
        return [self.pool[i] for _, _, i in ranked[:k]]


def _embed_with_retry(embed: Callable[[list[str]], list[list[float]]], batch: list[str]) -> list[list[float]]:
    """Ollama restarts a stopped model worker on the next request, so retry a failed batch."""
    import time
    from ..llm.base import ModelError
    for wait in (*EMBED_RETRY_WAITS, None):
        try:
            vectors = embed(batch)
            if len(vectors) != len(batch):
                raise ModelError(f"expected {len(batch)} embeddings, got {len(vectors)}")
            return vectors
        except ModelError:
            if wait is None:
                raise
            time.sleep(wait)
    raise AssertionError("unreachable")


def _number(x) -> bool:
    try:
        return x is not None and not math.isnan(float(x))
    except (TypeError, ValueError):
        return False


def render_examples(examples: list[dict]) -> str:
    """One line per example: arrival information and the ESI the triage nurse gave. ``examples``
    come most similar first; they are listed most similar LAST, next to the patient, because
    models weigh the last examples most (recency bias, Zhao et al. 2021)."""
    lines = []
    for n, c in enumerate(reversed(examples), 1):
        v = case_values(c)
        lines.append(f"{n}. {v['age']}-year-old {v['sex']}, arrived by {v['arrival_transport']}. "
                     f"Chief complaint: {v['chief_complaint']}. Vital signs: {v['vitals']}. "
                     f"Triage nurse's ESI: {c['reference']['esi']}")
    return "\n".join(lines)
