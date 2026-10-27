"""Remaining-useful-life (EXPERIMENTAL): hours from now until the failure (event end), learned from
the rows leading into anomaly events (<= 30 days before failure). With ~6-27 faults per farm this
is reported with its uncertainty and is only promoted when it beats a constant baseline.

Candidates (grouped by event in cross-validation, so a fault is never predicted by a
model that saw it): constant median (baseline), LightGBM quantile regression (P10/P50/P90),
Weibull accelerated-failure-time model.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd
from lifelines import WeibullAFTFitter
from sklearn.model_selection import GroupKFold

RUL_HORIZON_H = 720.0
RANDOM_STATE = 42


@dataclass
class RulResult:
    candidate: str
    mae_hours: float
    coverage_p10_p90: float | None  # share of true RUL inside the predicted interval
    n_events: int
    n_rows: int


def rul_frame(features: pd.DataFrame, frame: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    mask = (
        (frame["label"] == "anomaly")
        & frame["hours_to_failure"].between(0.0, RUL_HORIZON_H, inclusive="right")
    ).to_numpy()
    return features[mask], frame["hours_to_failure"].to_numpy()[mask], frame["event_id"].to_numpy()[mask]


def _qmodel(alpha: float):
    return lgb.LGBMRegressor(
        objective="quantile",
        alpha=alpha,
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=15,
        min_child_samples=100,
        random_state=RANDOM_STATE,
        verbose=-1,
    )


def evaluate_rul(x: pd.DataFrame, y: np.ndarray, groups: np.ndarray) -> list[RulResult]:
    n_events = len(np.unique(groups))
    if n_events < 4:
        return []
    folds = list(GroupKFold(n_splits=min(5, n_events)).split(x, y, groups))
    preds: dict[str, np.ndarray] = {
        k: np.zeros(len(y)) for k in ("baseline", "lgbm_p10", "lgbm_p50", "lgbm_p90", "weibull_aft")
    }
    xa = x.to_numpy(np.float32)
    for tr, te in folds:
        preds["baseline"][te] = np.median(y[tr])
        for a, key in ((0.1, "lgbm_p10"), (0.5, "lgbm_p50"), (0.9, "lgbm_p90")):
            preds[key][te] = _qmodel(a).fit(xa[tr], y[tr]).predict(xa[te])
        preds["weibull_aft"][te] = _weibull_predict(x.iloc[tr], y[tr], x.iloc[te])
    cover = float(np.mean((y >= preds["lgbm_p10"]) & (y <= preds["lgbm_p90"])))
    return [
        RulResult("baseline_median", float(np.mean(np.abs(preds["baseline"] - y))), None, n_events, len(y)),
        RulResult(
            "lightgbm_quantile", float(np.mean(np.abs(preds["lgbm_p50"] - y))), cover, n_events, len(y)
        ),
        RulResult("weibull_aft", float(np.mean(np.abs(preds["weibull_aft"] - y))), None, n_events, len(y)),
    ]


def _weibull_predict(x_tr: pd.DataFrame, y_tr: np.ndarray, x_te: pd.DataFrame) -> np.ndarray:
    cols = [c for c in x_tr.columns if x_tr[c].std() > 1e-6][:12]  # AFT is unstable with many/flat covariates
    if not cols:
        return np.full(len(x_te), np.median(y_tr))
    d = x_tr[cols].assign(T=np.maximum(y_tr, 0.1), E=1)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = WeibullAFTFitter(penalizer=0.1).fit(d, duration_col="T", event_col="E")
        return np.asarray(m.predict_median(x_te[cols])).ravel().clip(0, RUL_HORIZON_H)
    except Exception:  # convergence failure -> behave like the baseline, visibly worse in metrics
        return np.full(len(x_te), np.median(y_tr))


def fit_final(x: pd.DataFrame, y: np.ndarray) -> dict[str, lgb.LGBMRegressor]:
    xa = x.to_numpy(np.float32)
    return {k: _qmodel(a).fit(xa, y) for k, a in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))}
