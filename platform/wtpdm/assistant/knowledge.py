"""Retrieval corpus and BM25 ranking.

Sources: the platform guide (how scores, alerts, drift and retraining work), the
maintenance playbook (one chunk per sub-part failure mode) and each farm's champion model
card from the MLflow registry (refreshed when the champion changes). Local BM25: no
embedding API, no per-query cost, and the corpus is a few hundred chunks.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

import numpy as np
import yaml
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer

from wtpdm.logging import get_logger

log = get_logger("assistant.knowledge")
HERE = Path(__file__).parent
PLAYBOOK_PATH = HERE / "playbook.yaml"
KNOWLEDGE_DIR = HERE / "knowledge"
MODEL_CARD_REFRESH_SECONDS = 600

SUFFIXES = ("ures", "ure", "ing", "ies", "ed", "es", "s")
STOP_WORDS = ENGLISH_STOP_WORDS | {"does", "doe", "did", "tell", "explain", "know", "like", "mean", "meaning"}
BM25_K1, BM25_B = 1.5, 0.75


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str  # "guide" | "playbook" | "model_card"
    title: str
    text: str
    ref: str  # citation: document path, playbook id or model version


@dataclass
class Hit:
    chunk: Chunk
    score: float


def _stem(word: str) -> str:
    # Just enough stemming that "fail", "fails", "failed" and "failures" meet.
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def analyze(text: str) -> list[str]:
    # "Farm A" -> "farma": otherwise "a" is a stop word and every farm looks alike.
    text = re.sub(r"\bfarm\s+([abc])\b", r"farm\1", text.lower())
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text)
    tokens = [s for w in words if w not in STOP_WORDS and (s := _stem(w)) not in STOP_WORDS]
    return tokens + [f"{a} {b}" for a, b in pairwise(tokens)]


class Retriever:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.vectorizer = CountVectorizer(analyzer=analyze)
        # Titles are repeated so a title match carries extra weight.
        counts = self.vectorizer.fit_transform([f"{c.title} {c.title} {c.text}" for c in chunks])
        self.counts = counts.tocsc()
        n = len(chunks)
        df = np.asarray((self.counts > 0).sum(axis=0)).ravel()
        self.idf = np.log(1 + (n - df + 0.5) / (df + 0.5))
        doc_len = np.asarray(self.counts.sum(axis=1)).ravel()
        self.length_norm = BM25_K1 * (1 - BM25_B + BM25_B * doc_len / doc_len.mean())

    def search(self, query: str, k: int = 4, per_source: int = 3) -> list[Hit]:
        vocab = self.vectorizer.vocabulary_
        terms = sorted({vocab[t] for t in analyze(query) if t in vocab})
        if not terms:
            return []
        tf = self.counts[:, terms].toarray()
        scores = (self.idf[terms] * tf * (BM25_K1 + 1) / (tf + self.length_norm[:, None])).sum(axis=1)
        hits: list[Hit] = []
        taken: dict[str, int] = {}
        for i in scores.argsort()[::-1]:
            if scores[i] <= 0 or len(hits) == k:
                break
            chunk = self.chunks[i]
            if taken.get(chunk.source, 0) >= per_source:
                continue
            taken[chunk.source] = taken.get(chunk.source, 0) + 1
            hits.append(Hit(chunk, float(scores[i])))
        return hits


# ---------------------------------------------------------------- sources


def markdown_chunks(path: Path, source: str) -> list[Chunk]:
    """One chunk per `##` section (the H1 is the document title)."""
    text = path.read_text(encoding="utf-8")
    doc_title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), path.stem)
    chunks = []
    for i, section in enumerate(re.split(r"^## ", text, flags=re.M)[1:]):
        heading, _, body = section.partition("\n")
        chunks.append(
            Chunk(
                id=f"{source}:{path.stem}:{i}",
                source=source,
                title=f"{doc_title}: {heading.strip()}",
                text=body.strip(),
                ref=f"{path.stem}#{heading.strip().lower().replace(' ', '-')}",
            )
        )
    return chunks


@lru_cache
def playbook() -> dict:
    return yaml.safe_load(PLAYBOOK_PATH.read_text(encoding="utf-8"))


def playbook_chunks() -> list[Chunk]:
    out = []
    for code, entry in playbook()["entries"].items():
        for fm in entry["failure_modes"]:
            text = (
                f"{entry['name']} ({code}). Failure mode: {fm['mode']}. "
                f"Signals: {'; '.join(fm['signals'])}. Checks: {'; '.join(fm['checks'])}. "
                f"Actions: {'; '.join(fm['actions'])}."
            )
            out.append(
                Chunk(
                    f"playbook:{fm['id']}",
                    "playbook",
                    f"Playbook {fm['id']}: {entry['name']}",
                    text,
                    fm["id"],
                )
            )
    return out


def model_card_chunks() -> list[Chunk]:
    """Champion model cards, split by section. Best effort: the registry may be down."""
    from wtpdm.api import models_service  # registry access (cached per run)

    out: list[Chunk] = []
    for farm in ("A", "B", "C"):
        try:
            champion = next((v for v in models_service.versions(farm) if "champion" in v["aliases"]), None)
            if champion is None:
                continue
            card = models_service.card(farm, champion["version"])
        except Exception as exc:
            log.warning("model card unavailable", farm=farm, error=str(exc)[:200])
            continue
        label = f"{champion['model']} v{champion['version']}"
        for i, section in enumerate(re.split(r"^## ", card, flags=re.M)[1:]):
            heading, _, body = section.partition("\n")
            out.append(
                Chunk(
                    f"model_card:{farm}:{i}",
                    "model_card",
                    f"Model card {label}: {heading.strip()}",
                    body.strip(),
                    label,
                )
            )
    return out


class KnowledgeBase:
    """Static sources once; model cards refreshed periodically (champions change)."""

    def __init__(self, include_model_cards: bool = True):
        self._static = [c for p in sorted(KNOWLEDGE_DIR.glob("*.md")) for c in markdown_chunks(p, "guide")]
        self._static += playbook_chunks()
        self._include_cards = include_model_cards
        self._retriever: Retriever | None = None
        self._built_at = 0.0
        self._lock = threading.Lock()

    def retriever(self) -> Retriever:
        with self._lock:
            stale = time.monotonic() - self._built_at > MODEL_CARD_REFRESH_SECONDS
            if self._retriever is None or (self._include_cards and stale):
                cards = model_card_chunks() if self._include_cards else []
                self._retriever = Retriever(self._static + cards)
                self._built_at = time.monotonic()
            return self._retriever

    def search(self, query: str, k: int = 4) -> list[Hit]:
        return self.retriever().search(query, k=k)
