from pathlib import Path

import polars as pl
import pytest

from wtpdm.ingest.curate import IngestError, curate_event_file
from wtpdm.ingest.quality import stuck_mask
from wtpdm.ingest.source import SensorSpec, select_condition_sensors
from wtpdm.taxonomy import load_taxonomy

T = load_taxonomy()


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        # real descriptions from the three farms
        ("Temperature 1 planetary bearing A1", "gearbox.planetary_bearing"),
        ("Temperature in gearbox bearing on high speed shaft", "gearbox.hss_bearing"),
        ("Temperature oil in gearbox", "gearbox.oil"),
        ("Generator bearing temperature 1", "generator.bearing"),
        ("Temperature inside generator in stator windings phase 1", "generator.stator_winding"),
        ("Hydraulic pressure rotor brake A", "rotor_brake.caliper"),  # not hydraulics
        ("Hydraulic pressure azimuth circuit A", "hydraulics.pressure"),
        ("Axis1 Motor temperature KTY84", "pitch.drive"),
        ("Axis 2 Voltage battery 50%", "pitch.battery"),
        ("Current yaw motor A", "yaw.drive"),
        ("Temperature in HV transformer phase L1", "transformer.windings"),
        ("Drive train vibration axis Z", "vibration.drivetrain"),
    ],
)
def test_monitored_sensor_mapping(description, expected):
    cls = T.classify_sensor(description)
    assert (cls.role, cls.subcomponent_code) == ("monitored", expected)


@pytest.mark.parametrize(
    ("description", "kind"),
    [
        ("Total active power", "power"),
        ("Estimated windspeed", "wind_speed"),
        ("Ambient temperature", "ambient_temp"),
        ("Rotor speed 1", "rotor_speed"),
    ],
)
def test_condition_sensor_mapping(description, kind):
    assert T.classify_sensor(description).condition_kind == kind


def test_cabinet_ambient_is_not_the_weather():
    assert T.classify_sensor("Electrical cabinet ambient temperature").condition_kind is None


@pytest.mark.parametrize(
    ("description", "component"),
    [
        ("Gearbox failure", "gearbox"),
        ("Hydraulic group", "hydraulics"),
        ("stoerung 24VAC Versorgung Rotorbremse", "rotor_brake"),
        ('Turbine had several short standstills with failure "Schwingungen Umrichter"', "converter"),
        ("WEC in failure - hub battery charger defect", "pitch"),
        ("high temperature", None),  # genuinely unspecified - stays unclassified
    ],
)
def test_event_categorisation(description, component):
    assert T.classify_event(description) == component


def _spec(code, desc, kind=None):
    return SensorSpec("A", code, desc, None, ("avg",), False, False, "condition", None, kind)


def test_condition_selection_follows_pattern_preference_not_file_order():
    specs = [_spec("s1", "Wind speed 1", "wind_speed"), _spec("s2", "Wind speed", "wind_speed")]
    assert select_condition_sensors(specs, T)["wind_speed"] == "s2"


def test_stuck_mask_flags_long_constant_runs_only():
    values = [1.0, 2.0] + [5.0] * 40 + [3.0, 4.0]
    mask = stuck_mask(pl.Series(values), min_run=36)
    assert mask.sum() == 40 and not mask[0] and not mask[-1]


def _raw(asset_ids):
    n = len(asset_ids)
    return pl.DataFrame(
        {
            "time_stamp": [f"2020-01-01 00:{i:02d}:00" for i in range(n)],
            "asset_id": asset_ids,
            "id": list(range(n)),
            "train_test": ["train"] * (n - 1) + ["prediction"],
            "status_type_id": [0] * (n - 1) + [4],
            "sensor_0_avg": [10.0 + i for i in range(n)],
        }
    )


def test_curate_writes_typed_parquet(tmp_path: Path):
    spec = SensorSpec(
        "A", "sensor_0", "Ambient temperature", "°C", ("avg",), False, False, "condition", None, "x"
    )
    out = curate_event_file(
        _raw([7, 7, 7]), farm="A", event_id=3, turbine_id="A-1", sensors=[spec], out_dir=tmp_path
    )
    df = pl.read_parquet(out.path)
    assert df.columns == [
        "ts",
        "turbine_id",
        "event_id",
        "row_id",
        "split",
        "status",
        "sensor_0_avg",
        "operating",
    ]
    assert df["sensor_0_avg"].dtype == pl.Float32
    assert df["operating"].to_list() == [True, True, False]
    assert out.prediction_start == df["ts"][2]


def test_curate_rejects_file_with_several_turbines(tmp_path: Path):
    with pytest.raises(IngestError):
        curate_event_file(_raw([1, 2]), farm="A", event_id=1, turbine_id="A-1", sensors=[], out_dir=tmp_path)
