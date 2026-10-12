"""Input and output guardrails for the turbine assistant.

Input:  length limit, prompt-injection detection, unsafe-operation refusal (bypassing
        safety systems), off-topic filter, PII redaction before anything leaves for the
        LLM provider, per-client rate limit.
Output: secret scrubbing, grounding check (figures must appear in the retrieved
        context), length cap.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

MAX_INPUT_CHARS = 1000
MAX_OUTPUT_CHARS = 2500

INJECTION_PATTERNS = [
    r"ignore (all |any |the |your )?((previous|prior|above|earlier) )?(instructions|rules|prompts?)",
    r"disregard (all |the )?(previous|prior|above|your) (instructions|rules)",
    r"(reveal|show|print|repeat|leak) (me )?(your|the) (system |hidden |initial )?(prompt|instructions)",
    r"\bsystem prompt\b",
    r"you are now (a|an|in)\b",
    r"\b(developer|dan|god) mode\b",
    r"\bjailbreak",
    r"pretend (you are|to be) (not|no longer)",
    r"\bapi[_ -]?key\b",
]

# Advice that could get someone hurt or damage equipment. Matches intent to defeat a
# safety function, not general questions about how those systems work.
UNSAFE_PATTERNS = [
    r"\b(bypass|disable|override|defeat|jump(er)?|short[- ]?circuit|turn off|switch off|deactivate)\b.{0,40}"
    r"\b(safety|brake|braking|interlock|protection|alarm|trip|e-?stop|emergency stop|overspeed|lockout|limit switch|sensor)",
    r"\b(skip|ignore|without)\b.{0,30}\b(lockout|tagout|loto|safety (check|procedure|harness))",
    r"\bclimb\b.{0,40}\b(while|when).{0,20}\b(running|spinning|operating|rotating)",
    r"\b(keep|continue) (running|operating)\b.{0,70}\b(fault|alarm|damaged|cracked|leak)",
]

DOMAIN_TERMS = {
    "turbine", "turbines", "farm", "farms", "wind", "gearbox", "hydraulic", "hydraulics", "pitch", "blade",
    "generator", "transformer", "brake", "bearing", "vibration", "rul", "remaining", "life", "fault", "faults",
    "failure", "failures", "anomaly", "anomalies", "sensor", "sensors", "scada", "maintenance", "downtime",
    "derate", "derated", "idle", "alert", "alerts", "forecast", "prediction", "predictions", "model", "models",
    "p10", "p50", "p90", "twin", "dashboard", "health", "temperature", "pressure", "oil", "nacelle", "rotor",
    "yaw", "converter", "plc", "event", "events", "data", "dataset", "gold", "silver", "bronze", "medallion",
    "lightgbm", "mlflow", "probability", "warning", "status", "fleet", "component", "components", "power",
    "safety", "protection", "overspeed", "trip", "trips", "tripped", "alarm", "alarms", "shutdown", "repair",
    "technician", "inspection", "rpm", "speed", "wear", "leak", "leaking", "edp", "offshore", "onshore",
}
# BM25 fallback for on-topic questions with no domain word. Calibrated on eval/: the
# highest off-topic question scored 4.5 ("write me a poem about love").
ON_TOPIC_MIN_SCORE = 5.0
GREETINGS = re.compile(r"^\s*(hi|hello|hey|hiya|good (morning|afternoon|evening)|help|what can you do\??)\s*[!.?]*\s*$", re.I)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\s-]?){10,13}(?!\w)")
SECRET_RE = re.compile(r"\b(xai-[A-Za-z0-9]{16,}|gsk_[A-Za-z0-9]{16,}|sk-[A-Za-z0-9_-]{16,})\b")
NUMBER_RE = re.compile(r"(?<![\w.-])\d+(?:\.\d+)?(?![\w-])")


@dataclass
class InputCheck:
    blocked: bool
    text: str
    reason: str | None = None
    message: str | None = None
    flags: list[str] = field(default_factory=list)


def check_input(raw: str) -> InputCheck:
    text = (raw or "").strip()
    if not text:
        return InputCheck(True, text, "empty", "Please type a question about the wind turbines or the dashboard.")
    if len(text) > MAX_INPUT_CHARS:
        return InputCheck(True, text, "too_long",
                          f"That message is too long. Please keep questions under {MAX_INPUT_CHARS} characters.")
    lowered = text.lower()
    if any(re.search(p, lowered) for p in INJECTION_PATTERNS):
        return InputCheck(True, text, "prompt_injection",
                          "I can't change how I work or share my configuration. "
                          "I can answer questions about the turbines, their faults and this dashboard.")
    if any(re.search(p, lowered) for p in UNSAFE_PATTERNS):
        return InputCheck(True, text, "unsafe_operation",
                          "I can't help with bypassing or disabling turbine safety systems, or working around "
                          "safety procedures. That needs a qualified technician following the site's lockout "
                          "and safety rules. I can explain how a component works or what its readings mean.")
    flags = []
    redacted = EMAIL_RE.sub("[email removed]", text)
    redacted = PHONE_RE.sub("[phone removed]", redacted)
    if redacted != text:
        flags.append("pii_redacted")
    return InputCheck(False, redacted, flags=flags)


def is_greeting(text: str) -> bool:
    return bool(GREETINGS.match(text))


def is_on_topic(text: str, top_retrieval_score: float, mentions_turbine: bool) -> bool:
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    return mentions_turbine or bool(words & DOMAIN_TERMS) or top_retrieval_score >= ON_TOPIC_MIN_SCORE


OFF_TOPIC_MESSAGE = (
    "I can only help with this wind turbine platform: the turbines and farms, component faults, "
    "remaining-life predictions, alerts and how to read the dashboard. Try asking something like "
    "\"Why does Farm C have so many pitch faults?\""
)


def _numbers(text: str) -> set[float]:
    return {float(n) for n in NUMBER_RE.findall(text)}


def ungrounded_numbers(answer: str, context: str) -> list[str]:
    """Figures in the answer that don't appear in the context (small counts, years and
    simple rounding of a context figure are allowed)."""
    known = _numbers(context)
    missing = []
    for token in NUMBER_RE.findall(answer):
        value = float(token)
        if value <= 10 or 1900 <= value <= 2100:
            continue
        if any(abs(value - k) <= max(1.0, 0.02 * k) for k in known):
            continue
        missing.append(token)
    return missing


@dataclass
class OutputCheck:
    text: str
    flags: list[str] = field(default_factory=list)
    ungrounded: list[str] = field(default_factory=list)


UNICODE_DASHES = re.compile(r"[‐-―−]")
UNICODE_SPACES = re.compile(r"[   ]")


def check_output(answer: str, context: str, secrets: tuple[str, ...] = ()) -> OutputCheck:
    flags = []
    # Models often write "C‑12" with a non-breaking hyphen; normalise so turbine IDs and
    # figures are recognised by the grounding check (and display consistently).
    text = UNICODE_SPACES.sub(" ", UNICODE_DASHES.sub("-", answer)).strip()
    for secret in secrets:
        if secret and secret in text:
            text = text.replace(secret, "[redacted]")
            flags.append("secret_scrubbed")
    if SECRET_RE.search(text):
        text = SECRET_RE.sub("[redacted]", text)
        flags.append("secret_scrubbed")
    missing = ungrounded_numbers(text, context)
    if missing:
        flags.append("ungrounded_figures")
        text += ("\n\nNote: I couldn't verify these figures against the platform's data: "
                 + ", ".join(missing[:5]) + ". Please double-check them on the dashboard.")
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS].rsplit(" ", 1)[0] + "…"
        flags.append("truncated")
    return OutputCheck(text, flags, missing)


class RateLimiter:
    def __init__(self, max_requests: int, per_seconds: float):
        self.max, self.window = max_requests, per_seconds
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, client: str) -> bool:
        now = time.monotonic()
        q = self.hits[client]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max:
            return False
        q.append(now)
        return True
