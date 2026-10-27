"""Event-level evaluation in the spirit of the CARE benchmark.

In the dataset, an anomaly event's window [event_start, event_end] is the ABNORMAL PERIOD:
event_start is the onset of abnormal behaviour and event_end the failure / repair. The
rows of the prediction window before event_start are still normal operation.

Scored on the `prediction` windows only:
- anomaly event detected     = at least one alarm inside [event_start, event_end]
- warning before failure     = event_end - first in-window alarm (hours)
- earliness                  = share of the abnormal period still ahead at the first alarm
                               (1 = alarm at onset, 0 = at failure or missed)
- false alarms               = any alarm on a normal event (event level), and the share of
                               time in alarm on all normal-behaviour rows (normal events +
                               pre-onset rows of anomaly events) -> alarm days per turbine-year
- care_style_score           = mean(event F1, normal-event accuracy, mean earliness)
- diagnosis accuracy         = share of detected, component-labelled faults where the worst
                               sub-part at the first alarm belongs to the faulty component
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass
class EventResult:
    event_id: int
    turbine_id: str
    label: str
    component: str | None
    detected: bool
    first_alarm: pd.Timestamp | None
    warning_hours: float | None  # before failure (event_end)
    earliness: float
    pre_onset_alarm: bool  # alarm while the turbine was still behaving normally
    normal_rows: int
    normal_alarm_rows: int
    diagnosed_component: str | None


@dataclass
class Metrics:
    anomaly_events: int
    normal_events: int
    detected: int
    false_alarm_events: int
    pre_onset_alarm_events: int
    event_recall: float
    event_precision: float
    event_f1: float
    normal_accuracy: float
    earliness: float
    median_warning_hours: float | None
    false_alarm_days_per_turbine_year: float
    diagnosis_accuracy: float | None
    care_style_score: float

    def as_dict(self) -> dict:
        return asdict(self)


def event_results(
    frame: pd.DataFrame, alarm: np.ndarray, worst_component: pd.Series | None = None
) -> list[EventResult]:
    """frame: prediction-window rows with event_id, turbine_id, ts, label, event_start,
    event_end, event_component (in time order per event)."""
    df = frame.assign(_alarm=alarm)
    if worst_component is not None:
        df = df.assign(_worst=worst_component.to_numpy())
    out = []
    for event_id, g in df.groupby("event_id", sort=True):
        label = str(g["label"].iloc[0])
        start, end = g["event_start"].iloc[0], g["event_end"].iloc[0]
        if label == "anomaly":
            in_window = (g["ts"] >= start) & (g["ts"] <= end)
            normal_part = g[g["ts"] < start]
        else:
            in_window = pd.Series(False, index=g.index)
            normal_part = g
        hits = g.loc[in_window & g["_alarm"], "ts"]
        first = hits.min() if len(hits) else None
        warning = earliness = None
        diagnosed = None
        if first is not None:
            warning = float((end - first).total_seconds() / 3600)
            span = max((end - start).total_seconds(), 1.0)
            earliness = float(np.clip((end - first).total_seconds() / span, 0.0, 1.0))
            if "_worst" in g:
                diagnosed = g.loc[g["ts"] == first, "_worst"].iloc[0]
        component = g["event_component"].iloc[0]
        out.append(
            EventResult(
                event_id=int(event_id),
                turbine_id=str(g["turbine_id"].iloc[0]),
                label=label,
                component=component if pd.notna(component) else None,
                detected=first is not None,
                first_alarm=first,
                warning_hours=warning,
                earliness=earliness or 0.0,
                pre_onset_alarm=label == "anomaly" and bool(normal_part["_alarm"].any()),
                normal_rows=len(normal_part),
                normal_alarm_rows=int(normal_part["_alarm"].sum()),
                diagnosed_component=diagnosed if isinstance(diagnosed, str) else None,
            )
        )
    return out


def summarize(results: list[EventResult]) -> Metrics:
    anomalies = [r for r in results if r.label == "anomaly"]
    normals = [r for r in results if r.label == "normal"]
    tp = sum(r.detected for r in anomalies)
    fp = sum(r.normal_alarm_rows > 0 for r in normals)
    recall = tp / len(anomalies) if anomalies else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    normal_acc = 1 - fp / len(normals) if normals else 1.0
    earliness = float(np.mean([r.earliness for r in anomalies])) if anomalies else 0.0
    warnings = [r.warning_hours for r in anomalies if r.warning_hours is not None]
    normal_rows = sum(r.normal_rows for r in results)
    alarm_rows = sum(r.normal_alarm_rows for r in results)
    fa_days = (alarm_rows / normal_rows * 365) if normal_rows else 0.0
    diag = [r for r in anomalies if r.detected and r.component and r.diagnosed_component]
    diag_acc = (sum(r.diagnosed_component == r.component for r in diag) / len(diag)) if diag else None
    return Metrics(
        anomaly_events=len(anomalies),
        normal_events=len(normals),
        detected=tp,
        false_alarm_events=fp,
        pre_onset_alarm_events=sum(r.pre_onset_alarm for r in anomalies),
        event_recall=round(recall, 4),
        event_precision=round(precision, 4),
        event_f1=round(f1, 4),
        normal_accuracy=round(normal_acc, 4),
        earliness=round(earliness, 4),
        median_warning_hours=round(float(np.median(warnings)), 1) if warnings else None,
        false_alarm_days_per_turbine_year=round(fa_days, 2),
        diagnosis_accuracy=round(diag_acc, 4) if diag_acc is not None else None,
        care_style_score=round(float(np.mean([f1, normal_acc, earliness])), 4),
    )
