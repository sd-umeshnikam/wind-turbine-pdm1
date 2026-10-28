"""Normal-behaviour models (NBM): expected value of each monitored sensor given the
operating conditions (power, wind, ambient/nacelle temperature, rotor speed, pitch).

A component degrading shows up as the measured value drifting away from what a healthy
turbine would read under the same load and weather - the standard SCADA condition-
monitoring approach. Per sensor, several candidate regressors are compared on a
time-ordered holdout of normal data and the best one is kept.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

RANDOM_STATE = 42
FIT_SAMPLE_ROWS = 200_000  # per farm; plenty for 4-7 condition inputs
MLP_SAMPLE_ROWS = 60_000
MIN_RESIDUAL_STD = 1e-3


def _ridge():
    return make_pipeline(StandardScaler(), PolynomialFeatures(degree=2), Ridge(alpha=1.0))


def _lightgbm():
    return lgb.LGBMRegressor(
        n_estimators=300,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=50,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=1.0,
        random_state=RANDOM_STATE,
        verbose=-1,
    )


def _mlp():
    return make_pipeline(
        StandardScaler(),
        MLPRegressor(
            hidden_layer_sizes=(32, 16), early_stopping=True, max_iter=80, random_state=RANDOM_STATE
        ),
    )


# name -> (factory, max training rows)
CANDIDATES: dict[str, tuple[Callable[[], object], int]] = {
    "ridge_poly2": (_ridge, FIT_SAMPLE_ROWS),
    "lightgbm": (_lightgbm, FIT_SAMPLE_ROWS),
    "mlp": (_mlp, MLP_SAMPLE_ROWS),
}
BASELINE = "ridge_poly2"


@dataclass
class CandidateResult:
    name: str
    nrmse: float  # validation RMSE / std(y): < 1 means better than predicting the mean
    r2: float


@dataclass
class TargetModel:
    target: str
    subcomponent: str
    candidate: str
    model: object
    results: list[CandidateResult]
    # residual normalisation, per turbine (out-of-sample), plus a farm-wide fallback
    resid_mean: dict[str, float] = field(default_factory=dict)
    resid_std: dict[str, float] = field(default_factory=dict)
    fallback_mean: float = 0.0
    fallback_std: float = 1.0


def time_holdout(train: pd.DataFrame, fraction: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Last `fraction` of each event file's training rows (in time) form the validation set,
    so validation is always later than what the model saw."""
    rank = train.groupby("event_id")["ts"].rank(pct=True)
    return train[rank <= 1 - fraction], train[rank > 1 - fraction]


def _sample(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.sample(n=n, random_state=RANDOM_STATE) if len(df) > n else df


def _score(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float]:
    resid = y_true - y_pred
    var = float(np.var(y_true))
    mse = float(np.mean(resid**2))
    return (float(np.sqrt(mse / var)) if var > 0 else float("inf")), (1 - mse / var if var > 0 else 0.0)


def fit_target(
    target: str,
    subcomponent: str,
    conditions: list[str],
    fit_df: pd.DataFrame,
    val_df: pd.DataFrame,
    candidates: tuple[str, ...] = tuple(CANDIDATES),
) -> TargetModel:
    fit = fit_df[[*conditions, target]].dropna()
    val = val_df[[*conditions, target, "turbine_id"]].dropna()
    if len(fit) < 500 or len(val) < 100:
        raise ValueError(f"{target}: not enough normal data ({len(fit)} fit / {len(val)} validation rows)")
    results: list[CandidateResult] = []
    fitted: dict[str, object] = {}
    for name in candidates:
        factory, max_rows = CANDIDATES[name]
        sample = _sample(fit, max_rows)
        model = factory()
        model.fit(sample[conditions].to_numpy(np.float32), sample[target].to_numpy(np.float32))  # type: ignore[attr-defined]
        pred = model.predict(val[conditions].to_numpy(np.float32))  # type: ignore[attr-defined]
        nrmse, r2 = _score(val[target].to_numpy(np.float64), pred)
        results.append(CandidateResult(name, round(nrmse, 4), round(r2, 4)))
        fitted[name] = model

    best = min(results, key=lambda r: r.nrmse)
    model = fitted[best.name]
    tm = TargetModel(target, subcomponent, best.name, model, results)
    resid = val[target].to_numpy(np.float64) - model.predict(val[conditions].to_numpy(np.float32))  # type: ignore[attr-defined]
    val = val.assign(_resid=resid)
    tm.fallback_mean = float(np.mean(resid))
    tm.fallback_std = max(float(np.std(resid)), MIN_RESIDUAL_STD)
    for turbine, grp in val.groupby("turbine_id"):
        if len(grp) >= 50:
            tm.resid_mean[str(turbine)] = float(grp["_resid"].mean())
            tm.resid_std[str(turbine)] = max(float(grp["_resid"].std()), MIN_RESIDUAL_STD)
    return tm


def residual_z(tm: TargetModel, df: pd.DataFrame, conditions: list[str]) -> np.ndarray:
    """Standardised residual of `tm.target` for every row of df (NaN where inputs are missing)."""
    out = np.full(len(df), np.nan)
    x = df[conditions].to_numpy(np.float32)
    ok = ~np.isnan(x).any(axis=1) & df[tm.target].notna().to_numpy()
    if ok.any():
        pred = tm.model.predict(x[ok])  # type: ignore[attr-defined]
        resid = df[tm.target].to_numpy(np.float64)[ok] - pred
        turbines = df["turbine_id"].to_numpy()[ok]
        mean = np.array([tm.resid_mean.get(t, tm.fallback_mean) for t in turbines])
        std = np.array([tm.resid_std.get(t, tm.fallback_std) for t in turbines])
        out[ok] = (resid - mean) / std
    return out


def expected_value(tm: TargetModel, df: pd.DataFrame, conditions: list[str]) -> np.ndarray:
    """What a healthy turbine would read for `tm.target` under each row's conditions: the
    model prediction plus the turbine's typical offset (NaN where inputs are missing)."""
    out = np.full(len(df), np.nan)
    x = df[conditions].to_numpy(np.float32)
    ok = ~np.isnan(x).any(axis=1)
    if ok.any():
        turbines = df["turbine_id"].to_numpy()[ok]
        mean = np.array([tm.resid_mean.get(t, tm.fallback_mean) for t in turbines])
        out[ok] = tm.model.predict(x[ok]) + mean  # type: ignore[attr-defined]
    return out
