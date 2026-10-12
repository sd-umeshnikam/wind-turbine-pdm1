"""Groq chat client. Groq's API is OpenAI-compatible, so any compatible provider works
by changing GROQ_BASE_URL / GROQ_MODEL."""
from __future__ import annotations

import os
import time

import httpx

MAX_RETRY_WAIT_SECONDS = 8.0

GROQ_API_KEY_PLACEHOLDER = "your-groq-api-key-here"
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
# Largest general chat model on this Groq account (131k context). The earlier default,
# llama-3.3-70b-versatile, is no longer served - list current ones with GET {base}/models.
DEFAULT_MODEL = "openai/gpt-oss-120b"


def _key() -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    return "" if key == GROQ_API_KEY_PLACEHOLDER else key


def is_configured() -> bool:
    return bool(_key())


def api_key() -> str:
    return _key()


def model_name() -> str:
    return os.environ.get("GROQ_MODEL", DEFAULT_MODEL)


def chat(messages: list[dict], temperature: float = 0.2, max_tokens: int = 2000) -> str:
    base = os.environ.get("GROQ_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    body = {"model": model_name(), "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if model_name().startswith("openai/gpt-oss"):
        # Reasoning models spend tokens thinking before answering (hence the larger
        # max_tokens); "low" is plenty for answering from supplied context, and faster.
        body["reasoning_effort"] = os.environ.get("GROQ_REASONING_EFFORT", "low")
    for attempt in range(2):
        resp = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {_key()}"},
            json=body,
            timeout=float(os.environ.get("GROQ_TIMEOUT_SECONDS", "60")),
        )
        if resp.status_code != 429 or attempt:
            break
        # Rate-limited (Groq free tier has tight per-minute limits): wait as asked, once.
        time.sleep(min(float(resp.headers.get("retry-after", "2")), MAX_RETRY_WAIT_SECONDS))
    resp.raise_for_status()
    content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
    if not content:
        raise ValueError("model returned an empty answer")
    return content
