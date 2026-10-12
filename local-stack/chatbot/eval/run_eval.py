"""Measures the assistant against eval/*.json.

Retrieval: hit@3, hit@5 and MRR over questions with known correct chunks.
Guardrails: attack block rate (with the expected reason) and false-block rate on
legitimate questions, run end to end through the /api/chat endpoint.

Run inside the chatbot container:  python eval/run_eval.py
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402

import app as chatbot_app  # noqa: E402
import live_data  # noqa: E402


def retrieval_metrics(client: TestClient) -> dict:
    questions = json.loads((HERE / "retrieval_eval.json").read_text(encoding="utf-8"))
    retriever, known = chatbot_app.state["retriever"], chatbot_app.state["known_turbines"]
    hit3 = hit5 = 0
    reciprocal_ranks, misses, latencies = [], [], []
    for item in questions:
        boost = tuple(f"turbine:{t}" for t in live_data.turbine_ids_in(item["q"], known))
        started = time.perf_counter()
        ids = [h.chunk.id for h in retriever.search(item["q"], k=5, boost_ids=boost)]
        latencies.append((time.perf_counter() - started) * 1000)
        rank = next((i + 1 for i, cid in enumerate(ids) if cid in item["expect"]), None)
        hit3 += bool(rank and rank <= 3)
        hit5 += bool(rank)
        reciprocal_ranks.append(1 / rank if rank else 0)
        if not rank or rank > 3:
            misses.append({"q": item["q"], "rank": rank, "got": ids[:3]})
    n = len(questions)
    return {
        "questions": n,
        "hit@3": round(hit3 / n, 3),
        "hit@5": round(hit5 / n, 3),
        "mrr": round(sum(reciprocal_ranks) / n, 3),
        "median_retrieval_ms": round(statistics.median(latencies), 1),
        "misses_outside_top3": misses,
    }


def guardrail_metrics(client: TestClient) -> dict:
    cases = json.loads((HERE / "guardrail_eval.json").read_text(encoding="utf-8"))
    blocked_ok, wrong = 0, []
    for case in cases["must_block"]:
        g = client.post("/api/chat", json={"message": case["q"]}).json()["guardrail"]
        if g.get("blocked") and g.get("reason") == case["reason"]:
            blocked_ok += 1
        else:
            wrong.append({"q": case["q"], "expected": case["reason"], "got": g})
    false_blocks = []
    for q in cases["must_allow"]:
        g = client.post("/api/chat", json={"message": q}).json()["guardrail"]
        if g.get("blocked"):
            false_blocks.append({"q": q, "reason": g.get("reason")})
    return {
        "attacks": len(cases["must_block"]),
        "attack_block_rate": round(blocked_ok / len(cases["must_block"]), 3),
        "legit_questions": len(cases["must_allow"]),
        "false_block_rate": round(len(false_blocks) / len(cases["must_allow"]), 3),
        "wrongly_handled_attacks": wrong,
        "false_blocks": false_blocks,
    }


def main() -> None:
    # The eval sends ~25 requests from one client; lift the per-client limit for the run.
    chatbot_app.rate_limiter.max = 10_000
    # Measures retrieval and guardrails only - don't spend the Groq quota (it hit 429s).
    os.environ.pop("GROQ_API_KEY", None)
    with TestClient(chatbot_app.app) as client:
        report = {"retrieval": retrieval_metrics(client), "guardrails": guardrail_metrics(client)}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
