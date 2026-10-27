"""From per-sensor residual z-scores to sub-part / component / turbine health.

- sub-part score: RMS of its sensors' residual z, EWMA-smoothed over ~6 h per series
- component score: worst (max) of its sub-parts; turbine score: worst component
- health 0-100: 100 while the score is within normal noise (<= 1 sigma), decaying
  exponentially beyond it: score 4 -> ~37, score 7 -> ~14.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EWMA_SPAN_ROWS = 36  # 6 h of 10-minute data
HEALTH_DECAY = 3.0


def health_from_score(score: np.ndarray | pd.Series) -> np.ndarray:
    s = np.asarray(score, dtype=np.float64)
    return np.clip(100.0 * np.exp(-np.maximum(0.0, s - 1.0) / HEALTH_DECAY), 0.0, 100.0)


def subpart_scores(z: pd.DataFrame, targets: dict[str, list[str]], series_key: pd.Series) -> pd.DataFrame:
    """z: residual z per target column (rows in time order within each series).
    Returns one smoothed RMS-z column per sub-part."""
    out = {}
    for sub, cols in targets.items():
        present = [c for c in cols if c in z.columns]
        if not present:
            continue
        rms = np.sqrt(np.nanmean(np.square(z[present].to_numpy()), axis=1))
        out[sub] = (
            pd.Series(rms, index=z.index)
            .groupby(series_key.to_numpy())
            .transform(lambda s: s.ewm(span=EWMA_SPAN_ROWS, min_periods=6, ignore_na=True).mean())
        )
    return pd.DataFrame(out, index=z.index)


def component_scores(sub_scores: pd.DataFrame) -> pd.DataFrame:
    comps: dict[str, list[str]] = {}
    for sub in sub_scores.columns:
        comps.setdefault(sub.split(".")[0], []).append(sub)
    return pd.DataFrame(
        {c: sub_scores[subs].max(axis=1) for c, subs in comps.items()}, index=sub_scores.index
    )


def top_drivers(z_row: pd.Series, descriptions: dict[str, str], k: int = 3) -> list[dict]:
    """Largest absolute residuals at one timestamp - what an engineer should look at."""
    ranked = z_row.dropna().abs().sort_values(ascending=False).head(k)
    return [
        {"sensor": col, "description": descriptions.get(col, col), "z": round(float(z_row[col]), 2)}
        for col in ranked.index
    ]
