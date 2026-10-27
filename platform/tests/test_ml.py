import numpy as np
import pandas as pd

from wtpdm.ml import detectors
from wtpdm.ml.evaluate import event_results, summarize
from wtpdm.ml.health import health_from_score
from wtpdm.ml.nbm import fit_target, residual_z, time_holdout


def test_persistent_alarm_needs_consecutive_rows_within_one_series():
    score = np.array([5, 5, 5, 0, 5, 5, 5, 5], dtype=float)
    series = np.array([1, 1, 1, 1, 1, 1, 2, 2])
    alarm = detectors.persistent_alarm(score, threshold=1.0, series=series, rows=3)
    # run of 3 in series 1 -> alarm at idx 2; the run 4..5 is cut by the series change at idx 6
    assert alarm.tolist() == [False, False, True, False, False, False, False, False]


def test_health_is_full_within_noise_and_decays_beyond():
    h = health_from_score(np.array([0.0, 1.0, 4.0, 10.0]))
    assert h[0] == h[1] == 100.0
    assert 30 < h[2] < 45 and h[3] < 5


def _frame(events):
    """Hourly rows; each event's abnormal period is the LAST 4 rows (event_start..event_end)."""
    rows = []
    for event_id, label, alarms, component in events:
        n = len(alarms)
        t0 = pd.Timestamp("2020-01-10", tz="UTC")
        start, end = t0 + pd.Timedelta(hours=n - 4), t0 + pd.Timedelta(hours=n - 1)
        for i, a in enumerate(alarms):
            rows.append(
                {
                    "event_id": event_id,
                    "turbine_id": f"T{event_id}",
                    "ts": t0 + pd.Timedelta(hours=i),
                    "label": label,
                    "event_start": start,
                    "event_end": end,
                    "event_component": component,
                    "_a": a,
                    "_worst": "gearbox",
                }
            )
    return pd.DataFrame(rows)


def test_event_level_metrics_use_the_abnormal_period():
    df = _frame(
        [
            # 6 rows: 2 normal (pre-onset) + 4 abnormal; alarm at the onset row -> 3 h before failure
            (1, "anomaly", [0, 0, 1, 1, 1, 1], "gearbox"),
            (2, "anomaly", [1, 0, 0, 0, 0, 0], "pitch"),  # only a pre-onset alarm: missed + false alarm
            (3, "normal", [0, 0, 0, 0, 0, 0], None),  # correct silence
            (4, "normal", [0, 1, 0, 0, 0, 0], None),  # false alarm
        ]
    )
    m = summarize(event_results(df, df["_a"].to_numpy().astype(bool), df["_worst"]))
    assert (m.detected, m.false_alarm_events, m.pre_onset_alarm_events) == (1, 1, 1)
    assert m.event_recall == 0.5 and m.normal_accuracy == 0.5
    assert m.median_warning_hours == 3.0
    assert m.earliness == 0.5  # event 1 alarmed at onset (1.0), event 2 missed (0.0)
    assert m.diagnosis_accuracy == 1.0
    # 2 alarm rows over 2+2+6+6 = 16 normal-behaviour rows
    assert m.false_alarm_days_per_turbine_year == round(2 / 16 * 365, 2)


def test_time_holdout_validation_is_later_than_fit():
    ts = pd.date_range("2020-01-01", periods=100, freq="10min", tz="UTC")
    df = pd.DataFrame({"event_id": [1] * 50 + [2] * 50, "ts": list(ts[:50]) + list(ts[:50])})
    fit, val = time_holdout(df, 0.2)
    for e in (1, 2):
        assert fit[fit.event_id == e].ts.max() < val[val.event_id == e].ts.min()


def test_nbm_learns_condition_relationship_and_flags_a_shift():
    rng = np.random.default_rng(0)
    n = 6000
    power = rng.uniform(0, 2000, n)
    ambient = rng.uniform(-5, 30, n)
    temp = 20 + 0.02 * power + 0.8 * ambient + rng.normal(0, 0.5, n)
    df = pd.DataFrame(
        {
            "power": power,
            "ambient": ambient,
            "temp": temp,
            "turbine_id": "T1",
            "event_id": 1,
            "ts": pd.date_range("2020-01-01", periods=n, freq="10min", tz="UTC"),
        }
    )
    fit, val = time_holdout(df)
    tm = fit_target(
        "temp", "gearbox.oil", ["power", "ambient"], fit, val, candidates=("ridge_poly2", "lightgbm")
    )
    assert min(r.nrmse for r in tm.results) < 0.2  # explains >96% of variance
    faulty = df.tail(10).assign(temp=lambda d: d.temp + 10)  # +10 degC under the same load
    assert np.all(residual_z(tm, faulty, ["power", "ambient"]) > 5)
