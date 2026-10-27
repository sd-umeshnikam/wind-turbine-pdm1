"""Component / sub-part taxonomy: maps the dataset's free-text sensor and event
descriptions to platform concepts. Source of truth: config/taxonomy.yaml."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources

import yaml


@dataclass(frozen=True)
class SubcomponentDef:
    code: str  # fully qualified, e.g. "gearbox.planetary_bearing"
    name: str
    component_code: str
    patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class ComponentDef:
    code: str
    name: str
    subcomponents: tuple[SubcomponentDef, ...]


@dataclass(frozen=True)
class SensorClass:
    role: str  # monitored | condition | other
    subcomponent_code: str | None = None
    condition_kind: str | None = None


@dataclass(frozen=True)
class Taxonomy:
    components: tuple[ComponentDef, ...]
    conditions: dict[str, tuple[re.Pattern[str], ...]]
    required_conditions: tuple[str, ...]
    event_rules: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...]
    _subs: tuple[SubcomponentDef, ...] = field(default=(), repr=False)

    @property
    def subcomponents(self) -> tuple[SubcomponentDef, ...]:
        return self._subs

    def component(self, code: str) -> ComponentDef:
        return next(c for c in self.components if c.code == code)

    def classify_sensor(self, description: str) -> SensorClass:
        """Condition kinds win over sub-parts: a sensor like "Rotor speed" is a load input,
        not the health of the rotor."""
        text = _norm(description)
        for kind, patterns in self.conditions.items():
            if any(p.search(text) for p in patterns):
                return SensorClass(role="condition", condition_kind=kind)
        for sub in self._subs:
            if any(p.search(text) for p in sub.patterns):
                return SensorClass(role="monitored", subcomponent_code=sub.code)
        return SensorClass(role="other")

    def classify_event(self, description: str | None) -> str | None:
        text = _norm(description or "")
        for component, patterns in self.event_rules:
            if any(p.search(text) for p in patterns):
                return component
        return None


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _compile(patterns: list[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


@lru_cache
def load_taxonomy() -> Taxonomy:
    raw = yaml.safe_load(resources.files("wtpdm.config").joinpath("taxonomy.yaml").read_text("utf-8"))
    components = []
    subs: list[SubcomponentDef] = []
    for c in raw["components"]:
        defs = tuple(
            SubcomponentDef(
                code=f"{c['code']}.{s['code']}",
                name=s["name"],
                component_code=c["code"],
                patterns=_compile(s["patterns"]),
            )
            for s in c["subcomponents"]
        )
        subs.extend(defs)
        components.append(ComponentDef(code=c["code"], name=c["name"], subcomponents=defs))
    return Taxonomy(
        components=tuple(components),
        conditions={k: _compile(v) for k, v in raw["conditions"].items()},
        required_conditions=tuple(raw["required_conditions"]),
        event_rules=tuple((r["component"], _compile(r["patterns"])) for r in raw["event_categories"]),
        _subs=tuple(subs),
    )
