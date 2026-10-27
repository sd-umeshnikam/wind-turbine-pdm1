"""Anomaly detectors over sub-part health scores, compared under one protocol.

Every detector produces a per-row score and an alarm threshold; an alarm is raised only
when the score stays above the threshold for PERSISTENCE_ROWS consecutive rows (filters
single noisy readings). Unsupervised thresholds come from normal validation data only,
so no label information leaks into them.
"""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import GroupKFold

PERSISTENCE_ROWS = 12  # 2 h
THRESHOLD_QUANTILE = 0.995
RANDOM_STATE = 42


@dataclass
class DetectorOutput:
    name: str
    score: np.ndarray  # per row of the frame it was applied to
    threshold: float
    model: object | None = None


def persistent_alarm(
    score: np.ndarray, threshold: float, series: np.ndarray, rows: int = PERSISTENCE_ROWS
) -> np.ndarray:
    """True where score > threshold has held for `rows` consecutive rows of the same series."""
    above = np.nan_to_num(score, nan=-np.inf) > threshold
    alarm = np.zeros(len(score), dtype=bool)
    run = 0
    prev = None
    for i, (a, s) in enumerate(zip(above, series, strict=True)):
        run = run + 1 if (a and s == prev) else (1 if a else 0)
        prev = s
        alarm[i] = run >= rows
    return alarm


# ------------------------------------------------------------------ baseline


def threshold_baseline(turbine_score_val: np.ndarray, turbine_score_all: np.ndarray) -> DetectorOutput:
    """Turbine health score vs a high quantile of its normal-data distribution."""
    thr = float(np.nanquantile(turbine_score_val, THRESHOLD_QUANTILE))
    return DetectorOutput("threshold_baseline", turbine_score_all, thr)


# ------------------------------------------------------------------ isolation forest


def isolation_forest(sub_val: pd.DataFrame, sub_all: pd.DataFrame) -> DetectorOutput:
    """Multivariate: unusual COMBINATIONS of sub-part scores, not just one large one."""
    fit = sub_val.fillna(0.0).to_numpy()
    if len(fit) > 100_000:
        fit = fit[np.random.default_rng(RANDOM_STATE).choice(len(fit), 100_000, replace=False)]
    model = IsolationForest(n_estimators=200, random_state=RANDOM_STATE, n_jobs=1).fit(fit)
    score_val = -model.score_samples(sub_val.fillna(0.0).to_numpy())
    score_all = -model.score_samples(sub_all.fillna(0.0).to_numpy())
    return DetectorOutput(
        "isolation_forest", score_all, float(np.quantile(score_val, THRESHOLD_QUANTILE)), model
    )


# ------------------------------------------------------------------ supervised early warning


def supervised_features(sub_scores: pd.DataFrame, series: pd.Series) -> pd.DataFrame:
    worst = sub_scores.max(axis=1)
    grp = worst.groupby(series.to_numpy())
    return sub_scores.fillna(0.0).assign(
        worst=worst.fillna(0.0),
        worst_mean_24h=grp.transform(lambda s: s.rolling(144, min_periods=6).mean()).fillna(0.0),
        worst_max_24h=grp.transform(lambda s: s.rolling(144, min_periods=6).max()).fillna(0.0),
        worst_trend_24h=grp.transform(lambda s: s.diff(144)).fillna(0.0),
    )


def supervised_labels(frame: pd.DataFrame) -> np.ndarray:
    """1 = inside an anomaly event's abnormal period (event start to failure)."""
    return ((frame["label"] == "anomaly") & frame["in_event_window"]).to_numpy().astype(int)


def supervised_lgbm(
    features: pd.DataFrame, labels: np.ndarray, groups: np.ndarray, n_splits: int = 5
) -> DetectorOutput:
    """Out-of-fold probabilities with folds grouped by event: no event is ever scored by a
    model that saw it. The final model (for serving) is refit on everything."""
    pos = labels.sum()
    weight = min((len(labels) - pos) / max(pos, 1), 50.0)

    def model() -> lgb.LGBMClassifier:
        return lgb.LGBMClassifier(
            n_estimators=200,
            learning_rate=0.05,
            num_leaves=15,
            min_child_samples=100,
            subsample=0.8,
            subsample_freq=1,
            scale_pos_weight=weight,
            random_state=RANDOM_STATE,
            verbose=-1,
        )

    oof = np.zeros(len(labels))
    x = features.to_numpy(np.float32)
    for tr, te in GroupKFold(n_splits=min(n_splits, len(np.unique(groups)))).split(x, labels, groups):
        if labels[tr].sum() == 0:
            continue
        oof[te] = model().fit(x[tr], labels[tr]).predict_proba(x[te])[:, 1]
    final = model().fit(x, labels) if pos else None
    return DetectorOutput("supervised_lgbm", oof, 0.5, final)
