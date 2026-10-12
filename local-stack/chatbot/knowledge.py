"""Builds the chatbot's knowledge base: one text chunk per retrievable fact.

Sources, all read once at startup:
  - gold layer: fault_events (one card per real failure) and rul_labels (labelled
    pre-failure window per failure)
  - eda/outputs/fleet_summary.json + events_categorized.csv (farm summaries, readable
    fault categories)
  - project docs (EDA report, anomaly detection guide, ADRs, blueprint, dataset README)
    and the hand-written knowledge/*.md files

The gold *_features tables (0.3-3.9 GB each) are deliberately not loaded: live
per-turbine numbers come from the inference API instead (see live_data.py).
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from deltalake import DeltaTable

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT / "local-stack" / "pipeline"))
from common import gold_path, load_turbine_id_map, raw_datasets_dir  # noqa: E402

FARM_INFO = {
    "A": "onshore wind farm in Portugal (EDP open data), 86 sensor columns",
    "B": "offshore wind farm in Germany (anonymized), 257 sensor columns, the only farm with vibration sensors",
    "C": "offshore wind farm in Germany (anonymized), 957 sensor columns, 3-axis independent pitch, hydraulics and water cooling",
}

DOC_FILES = [
    "local-stack/chatbot/knowledge/components.md",
    "local-stack/chatbot/knowledge/glossary.md",
    "eda/EDA_REPORT.md",
    "docs/architecture/ANOMALY_DETECTION_GUIDE.md",
    "docs/architecture/BLUEPRINT.md",
    "docs/adr/0003-digital-twin-scope.md",
    "docs/adr/0004-local-hosting-substitutions.md",
]
DATASET_README = PLATFORM_ROOT.parent / "wind-turbine-scada-data-for-early-fault-detection" / "README.md"
MAX_CHUNK_CHARS = 1500


@dataclass
class Chunk:
    id: str
    title: str
    text: str
    source: str


def _split_markdown(path: Path, source: str) -> list[Chunk]:
    text = path.read_text(encoding="utf-8")
    # Image links and fenced code/diagram blocks (e.g. mermaid) add noise to retrieval
    # and can't be shown usefully in a chat answer.
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    chunks: list[Chunk] = []
    doc_title = path.stem
    for section in re.split(r"\n(?=#{1,3} )", text):
        lines = section.strip().splitlines()
        if not lines:
            continue
        heading = lines[0].lstrip("# ").strip() if lines[0].startswith("#") else doc_title
        body = "\n".join(lines[1:] if lines[0].startswith("#") else lines).strip()
        if not body:
            continue
        paragraphs, current = body.split("\n\n"), ""
        parts: list[str] = []
        for para in paragraphs:
            if current and len(current) + len(para) > MAX_CHUNK_CHARS:
                parts.append(current)
                current = ""
            current = f"{current}\n\n{para}" if current else para
        if current:
            parts.append(current)
        for i, part in enumerate(parts):
            chunks.append(Chunk(f"{source}#{len(chunks)}", f"{doc_title}: {heading}" + (f" ({i + 1})" if len(parts) > 1 else ""), part, source))
    return chunks


def _display_id(id_map: dict, farm: str, asset_id) -> str | None:
    n = id_map.get(farm, {}).get(str(asset_id))
    return f"{farm}-{n}" if n is not None else None


def _event_asset(farm: str, event_id: str) -> int | None:
    # gold fault_events fans each event out to several assets, so the turbine that
    # actually failed is taken from the event's own raw file (asset_id is constant per file).
    fp = raw_datasets_dir(farm) / f"comma_{event_id}.csv"
    if not fp.exists():
        return None
    return int(pd.read_csv(fp, usecols=["asset_id"], nrows=1)["asset_id"].iloc[0])


def _failure_chunks(id_map: dict) -> tuple[list[Chunk], dict[str, list[str]]]:
    events = DeltaTable(gold_path("fault_events")).to_pandas().drop_duplicates(["farm", "event_id"])
    categorized = pd.read_csv(PLATFORM_ROOT / "eda" / "outputs" / "events_categorized.csv", dtype={"event_id": str})
    categorized = categorized[categorized["event_label"] == "anomaly"].set_index(["farm", "event_id"])
    rul = DeltaTable(gold_path("rul_labels")).to_pandas()
    rul_window = rul.groupby(["farm", "event_id"])["hours_to_failure"].max()

    chunks: list[Chunk] = []
    per_turbine: dict[str, list[str]] = {}
    for ev in events.itertuples():
        key = (ev.farm, str(ev.event_id))
        category = categorized.loc[key, "category"] if key in categorized.index else ev.category
        asset = _event_asset(ev.farm, str(ev.event_id))
        turbine = _display_id(id_map, ev.farm, asset) if asset is not None else None
        days = (ev.event_end - ev.event_start).total_seconds() / 86400
        window = rul_window.get(key)
        text = (
            f"Failure event {ev.event_id} in Farm {ev.farm}"
            + (f" on turbine {turbine}" if turbine else "")
            + f". Fault category: {category}. Maintenance log description: \"{ev.event_description}\". "
            f"The labelled event lasted {days:.1f} days."
            + (f" The gold layer labels {window:.0f} hours of pre-failure data before it for RUL training." if window else "")
        )
        chunks.append(Chunk(f"gold:fault_events:{ev.farm}-{ev.event_id}", f"Failure {ev.farm}-{ev.event_id}: {category}", text, "gold layer: fault_events"))
        if turbine:
            per_turbine.setdefault(turbine, []).append(f"event {ev.event_id} ({category}: {ev.event_description})")
    return chunks, per_turbine


def _turbine_chunks(id_map: dict, per_turbine: dict[str, list[str]]) -> list[Chunk]:
    chunks = []
    for farm, assets in id_map.items():
        for n in sorted(assets.values()):
            turbine = f"{farm}-{n}"
            failures = per_turbine.get(turbine, [])
            # Farm details stay in the farm summary chunk; repeating them on 36 turbine
            # cards made "which farm is offshore?" retrieve turbines instead of farms.
            text = (
                f"Turbine {turbine} is in Farm {farm}. "
                + (f"It has {len(failures)} recorded failure(s): " + "; ".join(failures) + "."
                   if failures else "It has no recorded failure events in the dataset.")
            )
            chunks.append(Chunk(f"turbine:{turbine}", f"Turbine {turbine}", text, "gold layer + turbine_id_map"))
    return chunks


def _fleet_chunks() -> list[Chunk]:
    fs = json.loads((PLATFORM_ROOT / "eda" / "outputs" / "fleet_summary.json").read_text(encoding="utf-8"))
    chunks = []
    for farm, f in fs["farms"].items():
        warn = f.get("fault_to_downtime_hours", {})
        cats = ", ".join(f"{c} {n}" for c, n in f["anomaly_count_by_category"].items())
        text = (
            f"Farm {farm} is an {FARM_INFO.get(farm, '')}. It has {f['n_turbines']} turbines, "
            f"{f['n_anomaly_events']} failure (anomaly) events and {f['n_normal_events']} normal events. "
            f"Failures by category: {cats}."
            + (f" Median warning time from fault start to downtime: {warn['median_hours']} hours, measured on "
               f"{warn['n_events_computable']} of {warn['n_anomaly_events_total']} failures."
               if warn.get("median_hours") is not None else
               f" Warning time could be measured for {warn.get('n_events_computable', 0)} of its failures.")
        )
        chunks.append(Chunk(f"fleet:farm-{farm}", f"Farm {farm} summary", text, "eda/outputs/fleet_summary.json"))
    t, k = fs["fleet_totals"], fs["headline_kpis"]
    cats = ", ".join(f"{c} {n}" for c, n in t["anomaly_count_by_category"].items())
    w = k.get("fault_to_downtime_hours", {})
    chunks.append(Chunk(
        "fleet:totals", "Fleet totals",
        f"The fleet has {t['total_turbines']} turbines across 3 farms, {t['total_anomaly_events']} failure events and "
        f"{t['total_normal_events']} normal events. Failures by category across all farms: {cats}. "
        f"Most common named fault category: {k['most_common_named_fault_category']}. "
        f"Typical warning time before shutdown: median {w.get('median_hours')} hours "
        f"(half of cases {w.get('p25_hours')}-{w.get('p75_hours')} hours), based on {k.get('fault_to_downtime_coverage')}.",
        "eda/outputs/fleet_summary.json",
    ))
    return chunks


def build_knowledge_base() -> list[Chunk]:
    id_map = load_turbine_id_map()
    failure_chunks, per_turbine = _failure_chunks(id_map)
    chunks = failure_chunks + _turbine_chunks(id_map, per_turbine) + _fleet_chunks()
    for rel in DOC_FILES:
        path = PLATFORM_ROOT / rel
        if path.exists():
            chunks += _split_markdown(path, rel)
    if DATASET_README.exists():
        chunks += _split_markdown(DATASET_README, "dataset README")
    return chunks
