"""OpenAI-compatible chat-completions client with tool calling (Groq by default; any
compatible provider works by changing WTPDM_LLM_BASE_URL / WTPDM_LLM_MODEL)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from wtpdm.logging import get_logger
from wtpdm.settings import get_settings

MAX_RETRY_WAIT_SECONDS = 30.0
TIMEOUT_SECONDS = 60.0
ATTEMPTS = 4
# Provider 400s caused by the model itself (a malformed tool call); a new sample usually works.
RETRYABLE_CODES = {"tool_use_failed", "output_parse_failed"}

log = get_logger("llm")


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    try:
        wait = float(resp.headers.get("retry-after", ""))
    except ValueError:
        wait = 2.0 * (attempt + 1)
    return min(max(wait, 0.5), MAX_RETRY_WAIT_SECONDS)


class LLMError(RuntimeError):
    pass


class LLMRateLimited(LLMError):
    """The provider's usage limit is reached; `retry_after` seconds until it frees up."""

    def __init__(self, retry_after: float):
        self.retry_after = max(1.0, retry_after)
        minutes = round(self.retry_after / 60)
        when = f"about {minutes} min" if minutes >= 1 else f"{round(self.retry_after)} s"
        super().__init__(f"The language model's usage limit is reached; try again in {when}")


def _error_code(resp: httpx.Response) -> str:
    """The provider's error code (e.g. `tool_use_failed`), or "" when it gives none."""
    try:
        return str(resp.json()["error"].get("code") or "")
    except (ValueError, KeyError, TypeError, AttributeError):
        return ""


_TRY_AGAIN = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?")


def _provider_wait(resp: httpx.Response) -> float:
    """Seconds until the limit frees up: `retry-after`, else the provider's message."""
    try:
        return float(resp.headers["retry-after"])
    except (KeyError, ValueError):
        pass
    try:
        m = _TRY_AGAIN.search(resp.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        m = None
    if not m or not any(m.groups()):
        return 2.0
    h, mi, se = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mi * 60 + se


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text, as the model produced it


@dataclass
class LLMReply:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)

    def as_message(self) -> dict:
        """The assistant turn to append to the conversation before the tool results."""
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in self.tool_calls
            ]
        return msg


class ChatModel(Protocol):
    name: str

    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        max_tokens: int = 2000,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> LLMReply: ...


class OpenAICompatible:
    def __init__(self, api_key: str, base_url: str, model: str):
        self._key = api_key
        self._base = base_url.rstrip("/")
        self.name = model

    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        max_tokens: int = 2000,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> LLMReply:
        body: dict[str, Any] = {
            "model": self.name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.name.startswith("openai/gpt-oss"):
            # Reasoning model: "low" is enough to answer from tool results, and faster.
            body["reasoning_effort"] = "low"
        resp = None
        for attempt in range(ATTEMPTS):
            last = attempt == ATTEMPTS - 1
            try:
                resp = httpx.post(
                    f"{self._base}/chat/completions",
                    headers={"Authorization": f"Bearer {self._key}"},
                    json=body,
                    timeout=TIMEOUT_SECONDS,
                )
            except httpx.HTTPError as exc:
                if last:
                    raise LLMError(f"LLM provider unreachable: {type(exc).__name__}") from exc
                continue
            if resp.status_code == 429:
                wait = _provider_wait(resp)
                if last or wait > MAX_RETRY_WAIT_SECONDS:
                    # A quota (e.g. tokens per day) that will not free up within a retry.
                    raise LLMRateLimited(wait)
                time.sleep(_retry_after(resp, attempt))
                continue
            if resp.status_code == 400 and not last and _error_code(resp) in RETRYABLE_CODES:
                log.warning("llm retry", model=self.name, code=_error_code(resp), attempt=attempt + 1)
                continue
            if resp.status_code >= 500 and not last:
                time.sleep(_retry_after(resp, attempt))
                continue
            break
        if resp is None or resp.status_code >= 400:
            status = resp.status_code if resp is not None else "no response"
            code = _error_code(resp) if resp is not None else ""
            log.warning("llm error", model=self.name, status=status, code=code)
            raise LLMError(f"LLM provider returned {status}" + (f" ({code})" if code else ""))
        choice = resp.json()["choices"][0]["message"]
        calls = [
            ToolCall(c["id"], c["function"]["name"], c["function"].get("arguments") or "{}")
            for c in choice.get("tool_calls") or []
        ]
        return LLMReply(content=choice.get("content"), tool_calls=calls, usage=resp.json().get("usage", {}))


def default_model() -> ChatModel | None:
    """The configured model, or None when no API key is set (the assistant then reports
    itself unavailable instead of answering without grounding)."""
    s = get_settings()
    key = s.llm_api_key.get_secret_value().strip()
    if not key:
        return None
    return OpenAICompatible(key, s.llm_base_url, s.llm_model)


def suggestion_model() -> ChatModel | None:
    """The (smaller) model used for follow-up suggestions."""
    s = get_settings()
    key = s.llm_api_key.get_secret_value().strip()
    if not key:
        return None
    return OpenAICompatible(key, s.llm_base_url, s.llm_suggestion_model)
