"""Input and output guardrails for the maintenance assistant.

Input:  length limit, prompt-injection detection, refusal of unsafe operations (defeating
        safety systems), off-topic filter, PII redaction before anything leaves for the LLM
        provider, per-user rate limit.
Output: secret scrubbing, grounding check (figures must appear in the tool results or
        retrieved knowledge), length cap.
"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

MAX_INPUT_CHARS = 1000
MAX_OUTPUT_CHARS = 4000

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
    r"\b(password|secret|token)s?\b.{0,30}\b(of|for)\b.{0,20}\b(admin|user|database|db)\b",
]

# Intent to defeat a safety function, not questions about how those systems work.
UNSAFE_PATTERNS = [
    r"\b(bypass|disable|override|defeat|jump(er)?|short[- ]?circuit|turn off|switch off|deactivate)\b.{0,40}"
    r"\b(safety|brake|braking|interlock|protection|alarm|trip|e-?stop|emergency stop|overspeed|lockout|"
    r"limit switch|sensor)",
    r"\b(skip|ignore|without)\b.{0,30}\b(lockout|tagout|loto|safety (check|procedure|harness))",
    r"\bclimb\b.{0,40}\b(while|when).{0,20}\b(running|spinning|operating|rotating)",
    r"\b(keep|continue) (running|operating)\b.{0,70}\b(fault|alarm|damaged|cracked|leak)",
]

DOMAIN_TERMS = {
    "turbine",
    "turbines",
    "farm",
    "farms",
    "wind",
    "gearbox",
    "hydraulic",
    "hydraulics",
    "pitch",
    "blade",
    "blades",
    "generator",
    "transformer",
    "brake",
    "bearing",
    "bearings",
    "vibration",
    "rul",
    "remaining",
    "fault",
    "faults",
    "failure",
    "failures",
    "anomaly",
    "anomalies",
    "sensor",
    "sensors",
    "scada",
    "maintenance",
    "downtime",
    "alert",
    "alerts",
    "alarm",
    "alarms",
    "model",
    "models",
    "health",
    "twin",
    "temperature",
    "pressure",
    "oil",
    "nacelle",
    "rotor",
    "yaw",
    "converter",
    "event",
    "events",
    "data",
    "drift",
    "retrain",
    "retraining",
    "champion",
    "challenger",
    "mlflow",
    "detector",
    "fleet",
    "component",
    "components",
    "power",
    "safety",
    "inspection",
    "inspect",
    "repair",
    "replace",
    "technician",
    "wear",
    "leak",
    "worst",
    "critical",
    "severity",
    "acknowledge",
    "resolve",
    "assigned",
    "queue",
    "replay",
    "residual",
    "expected",
    "nbm",
    "score",
    "evaluation",
    "precision",
    "recall",
    "lead",
    "warning",
    "playbook",
    "recommend",
    "recommendation",
    "recommendations",
    "cooling",
    "winding",
    "windings",
    "battery",
    "pump",
    "caliper",
    "cabinet",
    "slip",
    "hub",
    "subpart",
    "sub-part",
    "status",
    "changed",
    "visit",
    "today",
    "summary",
    "summarise",
    "summarize",
    "overview",
    "trend",
    "trends",
    "dashboard",
}
TURBINE_ID = re.compile(r"\b[ABC]-\d{1,2}\b", re.I)
GREETING = re.compile(
    r"^\s*(hi|hello|hey|good (morning|afternoon|evening)|help|what can you do\??|thanks?( you)?)"
    r"\s*[!.?]*\s*$",
    re.I,
)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\s-]?){10,13}(?!\w)")
SECRET_RE = re.compile(
    r"\b(xai-[A-Za-z0-9]{16,}|gsk_[A-Za-z0-9]{16,}|sk-[A-Za-z0-9_-]{16,}|eyJ[\w-]{20,}\.[\w-]+\.[\w-]+)"
)
NUMBER_RE = re.compile(r"(?<![\w.-])\d+(?:\.\d+)?(?![\w-])")
CONTEXT_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
CLOCK_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")  # times of day: rounding a minute is fine
THOUSANDS_RE = re.compile("(?<=\\d)[ ," + chr(0x00A0) + chr(0x202F) + "](?=\\d{3}\\b)")
PERCENT_RE = re.compile(r"\s?%")
# Hyphen..horizontal bar and minus sign; no-break, figure and narrow no-break spaces.
UNICODE_DASHES = re.compile("[" + chr(0x2010) + "-" + chr(0x2015) + chr(0x2212) + "]")
UNICODE_SPACES = re.compile("[" + chr(0x00A0) + chr(0x2007) + chr(0x202F) + "]")

INJECTION_MESSAGE = "I can't do that. Ask me about the fleet, alerts, models or maintenance."
UNSAFE_MESSAGE = (
    "I can't help with bypassing or disabling safety systems. Follow the site safety procedure and "
    "contact a qualified technician."
)
OFF_TOPIC_MESSAGE = (
    "I can only help with this wind fleet: turbine and component health, alerts, models, drift, "
    "data and maintenance."
)


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
        return InputCheck(True, text, "empty", "Type a question.")
    if len(text) > MAX_INPUT_CHARS:
        return InputCheck(
            True, text, "too_long", f"Please keep questions under {MAX_INPUT_CHARS} characters."
        )
    lowered = text.lower()
    if any(re.search(p, lowered) for p in INJECTION_PATTERNS):
        return InputCheck(True, text, "prompt_injection", INJECTION_MESSAGE)
    if any(re.search(p, lowered) for p in UNSAFE_PATTERNS):
        return InputCheck(True, text, "unsafe_operation", UNSAFE_MESSAGE)
    flags = []
    redacted = PHONE_RE.sub("[phone removed]", EMAIL_RE.sub("[email removed]", text))
    if redacted != text:
        flags.append("pii_redacted")
    return InputCheck(False, redacted, flags=flags)


def is_greeting(text: str) -> bool:
    return bool(GREETING.match(text))


def is_on_topic(text: str, retrieval_score: float, has_context: bool, min_score: float = 5.0) -> bool:
    """Domain word, turbine id, an entity open on screen, or a strong knowledge match."""
    words = set(re.findall(r"[a-z0-9-]+", text.lower()))
    return (
        bool(words & DOMAIN_TERMS)
        or bool(TURBINE_ID.search(text))
        or has_context
        or retrieval_score >= min_score
    )


def _numbers(text: str) -> set[float]:
    """Every number in the grounding context, including those inside ranges ("65-80") and
    identifiers ("sensor_35"), which the answer may legitimately quote on their own."""
    return {float(n) for n in CONTEXT_NUMBER_RE.findall(text)}


def ungrounded_numbers(answer: str, context: str) -> list[str]:
    """Figures in the answer that appear nowhere in the grounding context. Small counts,
    years, clock times and rounding of a context figure are allowed."""
    known = _numbers(context)
    text = THOUSANDS_RE.sub("", CLOCK_RE.sub(" ", answer))  # "1 030" / "1,030" -> "1030"
    missing = []
    for m in NUMBER_RE.finditer(text):
        token, value = m.group(), float(m.group())
        if value <= 10 or 1900 <= value <= 2100:
            continue
        # A share quoted as a percentage ("78 %" for 0.78) is the same figure.
        candidates = [value, value / 100] if PERCENT_RE.match(text, m.end()) else [value]
        tolerance = [(c, 0.51 if c == value else 0.0051) for c in candidates]
        if any(abs(c - k) <= max(tol, 0.02 * abs(k)) for c, tol in tolerance for k in known):
            continue
        missing.append(token)
    return missing


@dataclass
class OutputCheck:
    text: str
    flags: list[str] = field(default_factory=list)
    ungrounded: list[str] = field(default_factory=list)


def check_output(answer: str, context: str, secrets: tuple[str, ...] = ()) -> OutputCheck:
    flags = []
    # Models often write ids with a non-breaking hyphen (U+2011); normalise so ids and figures match.
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
        text += (
            "\n\n_Unverified figures (not found in the platform data I retrieved): "
            + ", ".join(missing[:5])
            + "._"
        )
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS].rsplit(" ", 1)[0] + "…"
        flags.append("truncated")
    return OutputCheck(text, sorted(set(flags)), missing)


class RateLimiter:
    def __init__(self, max_requests: int, per_seconds: float):
        self.max, self.window = max_requests, per_seconds
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max:
                return False
            q.append(now)
            return True
