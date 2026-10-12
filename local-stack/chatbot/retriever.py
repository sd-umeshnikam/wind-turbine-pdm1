from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer

from knowledge import Chunk

SUFFIXES = ("ures", "ure", "ing", "ies", "ed", "es", "s")
CURATED_PREFIX = "local-stack/chatbot/knowledge/"
CURATED_BOOST = 1.1
# Question filler that sklearn's list misses ("does" also stems to "doe").
STOP_WORDS = ENGLISH_STOP_WORDS | {"does", "doe", "did", "tell", "explain", "know", "like", "mean", "meaning"}
BM25_K1, BM25_B = 1.5, 0.75


def _stem(word: str) -> str:
    # Just enough stemming that "fail", "fails", "failed" and "failures" meet.
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def analyze(text: str) -> list[str]:
    # "Farm A" -> "farma": otherwise "a" is dropped as a stop word and every farm looks alike.
    text = re.sub(r"\bfarm\s+([abc])\b", r"farm\1", text.lower())
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text)
    tokens = [s for w in words if w not in STOP_WORDS and (s := _stem(w)) not in STOP_WORDS]
    return tokens + [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]


@dataclass
class Hit:
    chunk: Chunk
    score: float


class Retriever:
    """Local BM25 ranking: no embeddings API needed (Groq doesn't serve embedding
    models), no per-query cost, and the corpus is only a few hundred chunks. BM25
    rather than TF-IDF cosine, which over-ranked one-line failure cards above the
    paragraphs that actually explain a component."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.vectorizer = CountVectorizer(analyzer=analyze)
        # Titles are repeated so a match on "Turbine C-3" or "Gearbox" carries extra weight.
        self.counts = self.vectorizer.fit_transform([f"{c.title} {c.title} {c.text}" for c in chunks]).tocsc()
        n = len(chunks)
        df = np.asarray((self.counts > 0).sum(axis=0)).ravel()
        self.idf = np.log(1 + (n - df + 0.5) / (df + 0.5))
        doc_len = np.asarray(self.counts.sum(axis=1)).ravel()
        self.length_norm = BM25_K1 * (1 - BM25_B + BM25_B * doc_len / doc_len.mean())

    def scores(self, query: str) -> np.ndarray:
        vocab = self.vectorizer.vocabulary_
        terms = sorted({vocab[t] for t in analyze(query) if t in vocab})
        if not terms:
            return np.zeros(len(self.chunks))
        tf = self.counts[:, terms].toarray()
        return (self.idf[terms] * tf * (BM25_K1 + 1) / (tf + self.length_norm[:, None])).sum(axis=1)

    def search(self, query: str, k: int = 5, boost_ids: tuple[str, ...] = (), per_source: int = 3) -> list[Hit]:
        scores = self.scores(query)
        top_score = scores.max() if len(scores) else 0.0
        for i, chunk in enumerate(self.chunks):
            if chunk.id in boost_ids:
                # A turbine named in the question (or open on screen) always leads.
                scores[i] += top_score + 1.0
            elif chunk.source.startswith(CURATED_PREFIX):
                scores[i] *= CURATED_BOOST
        hits: list[Hit] = []
        taken: dict[str, int] = {}
        # At most `per_source` hits per source, so e.g. five near-identical failure cards
        # can't crowd out the explanation the question was actually after.
        for i in scores.argsort()[::-1]:
            if scores[i] <= 0 or len(hits) == k:
                break
            chunk = self.chunks[i]
            if chunk.id not in boost_ids and taken.get(chunk.source, 0) >= per_source:
                continue
            taken[chunk.source] = taken.get(chunk.source, 0) + 1
            hits.append(Hit(chunk, float(scores[i])))
        return hits
