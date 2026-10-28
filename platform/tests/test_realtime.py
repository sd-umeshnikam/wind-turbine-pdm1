from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from wtpdm.db.models import Severity
from wtpdm.ml.health import calibrated_health
from wtpdm.realtime import drift
from wtpdm.realtime.alerts import CLEAR_ROWS, condition_cleared, severity_for
from wtpdm.realtime.champion import quantile_profile
from wtpdm.realtime.replay import TickClock, TurbineStream, merge_windows
from wtpdm.realtime.scorer import OnlineScorer

T0 = datetime(2020, 1, 1, tzinfo=UTC)


def _rows(start: int, n: int, event_id: int, label: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [T0 + timedelta(minutes=10 * (start + i)) for i in range(n)],
            "turbine_id": ["A-1"] * n,
            "event_id": [event_id] * n,
            "label": [label] * n,
            "sensor_1_avg": [float(event_id)] * n,
        }
    )


# ---------------------------------------------------------------- replay


def test_tick_clock_keeps_exact_long_run_speed():
    assert [TickClock(60, 10).rows() for _ in range(3)] == [1, 1, 1]
    half = TickClock(30, 10)
    assert sum(half.rows() for _ in range(10)) == 5
    fast = TickClock(600, 10)
    assert fast.rows() == 10


def test_merge_windows_orders_dedups_and_prefers_the_anomaly_event():
    normal = _rows(0, 10, event_id=1, label="normal")
    anomaly = _rows(5, 10, event_id=2, label="anomaly")  # overlaps rows 5-9
    merged = merge_windows([normal, anomaly])
    assert merged.height == 15
    assert merged["ts"].is_sorted()
    assert merged.filter(pl.col("ts") >= T0 + timedelta(minutes=50))["event_id"].unique().to_list() == [2]


def test_turbine_stream_never_crosses_the_loop_point(tmp_path: Path):
    path = tmp_path / "t.parquet"
    _rows(0, 5, 1, "normal").write_parquet(path)
    stream = TurbineStream("A-1", "A", path, total=5)
    assert stream.next_rows(3).height == 3
    assert stream.next_rows(3).height == 2  # stops at the end instead of wrapping mid-batch
    again = stream.next_rows(3)
    assert (stream.cycle, again.height, again["ts"][0]) == (1, 3, T0)


def test_scorer_drops_history_when_the_replay_loops():
    scorer = OnlineScorer("A", engine=None, lake_root=Path("."))  # type: ignore[arg-type]
    first = _rows(0, 4, 1, "normal").to_pandas()
    scorer.buffers = {"A-1": first}
    later = _rows(4, 2, 1, "normal").to_pandas()
    assert scorer._frame(later)["is_new"].tolist() == [False] * 4 + [True] * 2
    looped = _rows(0, 2, 1, "normal").to_pandas()
    assert scorer._frame(looped)["is_new"].tolist() == [True, True]


# ---------------------------------------------------------------- alerts


def test_severity_follows_health_and_escalates_with_persistence():
    assert severity_for(70, timedelta(0)) == Severity.LOW
    assert severity_for(40, timedelta(0)) == Severity.MEDIUM
    assert severity_for(20, timedelta(0)) == Severity.HIGH
    assert severity_for(5, timedelta(0)) == Severity.CRITICAL
    assert severity_for(40, timedelta(hours=48)) == Severity.HIGH
    assert severity_for(5, timedelta(hours=72)) == Severity.CRITICAL


def test_condition_clears_only_after_six_hours_below_the_hysteresis_level():
    thr = 1.0
    below = np.full(CLEAR_ROWS, 0.5)
    assert condition_cleared(below, thr)
    assert not condition_cleared(below[:-1], thr)  # not long enough yet
    near = np.full(CLEAR_ROWS, 0.95)  # under the threshold but above 90% of it
    assert not condition_cleared(near, thr)
    gap = below.copy()
    gap[-1] = np.nan  # missing data never counts as "normal"
    assert not condition_cleared(gap, thr)


# ---------------------------------------------------------------- drift


def _reference(rng) -> dict:
    temp = rng.normal(10, 5, 20_000)
    score = np.abs(rng.normal(1, 0.3, 20_000))
    return {
        "conditions": {"sensor_0_avg": quantile_profile(temp)},
        "turbine_score": quantile_profile(score),
        "alarm_rate": 0.005,
    }


def test_psi_is_small_for_the_same_distribution_and_large_for_a_shift():
    rng = np.random.default_rng(0)
    ref = quantile_profile(rng.normal(0, 1, 20_000))
    assert drift.psi(ref, rng.normal(0, 1, 5_000)) < 0.05
    assert drift.psi(ref, rng.normal(1.5, 1, 5_000)) > drift.PSI_THRESHOLD


def test_drift_evaluation_triggers_only_on_model_validity_metrics():
    rng = np.random.default_rng(1)
    ref = _reference(rng)
    # Same world: nothing breached.
    same = drift.evaluate(
        ref,
        {"sensor_0_avg": rng.normal(10, 5, 4_000)},
        np.abs(rng.normal(1, 0.3, 4_000)),
        np.zeros(4_000, bool),
    )
    assert not any(r.breached for r in same)
    # A narrow seasonal window: PSI breaches, but it does not ask for a retrain.
    season = drift.evaluate(
        ref,
        {"sensor_0_avg": rng.normal(14, 1, 4_000)},
        np.abs(rng.normal(1, 0.3, 4_000)),
        np.zeros(4_000, bool),
    )
    assert any(r.metric == "psi_input" and r.breached for r in season)
    assert not any(r.breached and r.triggers_retrain for r in season)
    # Conditions outside the training support and residuals shifted: retrain.
    shifted = drift.evaluate(
        ref,
        {"sensor_0_avg": rng.normal(40, 3, 4_000)},
        np.abs(rng.normal(3, 0.5, 4_000)),
        np.zeros(4_000, bool),
    )
    triggered = {r.metric for r in shifted if r.breached and r.triggers_retrain}
    assert triggered == {"out_of_support", "residual_shift"}


def test_alert_rate_is_reported_but_never_triggers_a_retrain():
    rng = np.random.default_rng(2)
    ref = _reference(rng)
    alarms = np.zeros(4_000, bool)
    alarms[:30] = True  # 0.75%: below the limit max(3 x 0.5%, 1%) = 1.5%
    res = {r.metric: r for r in drift.evaluate(ref, {}, np.ones(4_000), alarms)}
    assert not res["alert_rate"].breached
    alarms[:200] = True  # 5%
    res = {r.metric: r for r in drift.evaluate(ref, {}, np.ones(4_000), alarms)}
    assert res["alert_rate"].breached and not res["alert_rate"].triggers_retrain


def test_calibrated_health_reads_the_same_on_any_score_scale():
    # 100 at the normal median, 50 at the alarm level, 25 one step further - whatever the units.
    for median, alarm in [(1.0, 3.0), (2.5, 9.2)]:
        step = alarm - median
        h = calibrated_health(np.array([0.0, median, alarm, alarm + step, np.nan]), median, alarm)
        assert np.allclose(h[:4], [100, 100, 50, 25])
        assert np.isnan(h[4])
