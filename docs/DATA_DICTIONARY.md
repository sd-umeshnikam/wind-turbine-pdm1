# Data dictionary: Wind PdM Platform v2

## Source: the CARE dataset

The source is three wind farms of 10-minute SCADA data:
- **Farm A:** onshore, Portugal (EDP open data). 5 turbines, 54 signals.
- **Farm B:** offshore, Germany. 9 turbines, 63 signals.
- **Farm C:** offshore, Germany. 22 turbines, 238 signals.

Each of the 95 event files (`comma_<event_id>.csv`, 44 anomaly and 51 normal) is one
turbine's year of normal `train` history followed by a `prediction` window that leads into
a labelled outcome. **The file name is the only event→turbine link.** Timestamps are
anonymised and shifted per turbine (2014–2029), so only order and durations within a
turbine are meaningful.

A signal is reported as up to four statistics (`_avg`, `_min`, `_max`, `_std`). The platform
models the average. A signal that has only one statistic is stored without a suffix.

## Curated lake (`lake` volume, `/data/lake`)

| Path | Content |
|---|---|
| `curated/farm=X/event=N.parquet` | One validated event file: `ts`, `turbine_id`, `event_id`, `row_id`, `split` (train / prediction), `status` (harmonised operating status), `operating` (normal-operation flag), signal columns |
| `catalog/farm=X/sensors.parquet` | Sensor catalog: code, description, unit, statistics, angle and counter flags, role (`monitored` / `condition` / `other`), sub-part, condition kind |
| `catalog/farm=X/events.parquet` | CARE events: id, turbine, label, description, component (from the description), window / prediction / event start and end |
| `catalog/farm=X/turbines.json` | asset id → turbine id (`A-1` …) |
| `catalog/farm=X/coverage.json` | monitored sensors per component and sub-part |
| `catalog/farm=X/data_quality.json` | per sensor: rows, missing %, stuck % (consecutive identical readings), out-of-range % |
| `catalog/farm=X/conditions.json` | operating-condition sensors chosen as model inputs |
| `replay/farm=X/turbine=T.parquet` | each turbine's replay timeline (its events in data-time order) |
| `reference/<model>-v<N>.json` | per model version: score distributions on training data (drift reference) and the health calibration profile |
| `reports/` | fleet-wide coverage, data-quality and condition reports |

`data_version` (in the API and on MLflow runs) is a SHA-256 fingerprint of a farm's
catalog files. It changes only when re-ingestion changes the data.

## Taxonomy

`platform/wtpdm/config/taxonomy.yaml` maps sensor descriptions to components and sub-parts,
and to operating-condition kinds, by pattern.

| Component | Sub-parts |
|---|---|
| gearbox | planetary_bearing, hss_bearing, oil |
| generator | bearing, stator_winding, cooling, slip_ring |
| rotor | main_bearing, hub |
| pitch | drive, battery |
| rotor_brake | caliper |
| hydraulics | oil, pressure, pump |
| yaw | drive |
| transformer | windings, oil |
| converter | power_electronics, cooling |
| electrical | cabinets |
| vibration | drivetrain, tower_nacelle |

Condition kinds are `power`, `wind_speed`, `rotor_speed`, `ambient_temp`, `nacelle_temp`,
`pitch_angle` and `reactive_power`. Every farm must provide `power`, `wind_speed` and
`ambient_temp`.

## Platform database (`wtpdm`, TimescaleDB)

| Table | Content | Key columns |
|---|---|---|
| `farm`, `turbine` | Assets | `turbine.id` = `A-1`, unique (`farm_id`, `asset_id`) |
| `component`, `subcomponent` | Taxonomy | `subcomponent.code` = `gearbox.oil` |
| `sensor` | Catalog per farm | `code`, `description`, `unit`, `role`, `subcomponent_code`, `condition_kind` |
| `event` | CARE events | `source_event_id`, `turbine_id`, `label` (anomaly / normal), `component_code`, window / prediction / event times |
| `telemetry` | **Hypertable.** Replayed readings, long format | `turbine_id`, `ts`, `sensor_id`, `value` |
| `health_score` | **Hypertable.** Scores per turbine, sub-part and time; `subcomponent_code = 'turbine'` holds the turbine row | `health` (0–100, 50 = alarm level), `residual_z`, `anomaly_score`, `alarm`, `model_version` |
| `replay_state` | Replay cursor per turbine | `cursor_ts`, `position` / `total_rows`, `cycle`, `source_event_id`, `operating_status` (0 normal … 5 other) |
| `alert` | Work queue: one active alert per turbine | `severity`, `status` (open → acknowledged → resolved), `drivers` (sensor, description, z), `condition_active`, `assignee`, data times |
| `alert_note` | Notes and resolutions | `author`, `body` |
| `audit_log` | Every user and system action | `actor`, `action` (`alert.acknowledge`, `model.promote`, `auth.login_failed`, …), `entity`, `details` |
| `model_deployment` | Registry alias history mirrored from MLflow | `model_name`, `version`, `alias`, `validation`, `metrics` |
| `drift_report` | Drift metrics per check | `metric` (psi_input, out_of_support, residual_shift, alert_rate), `feature`, `value`, `threshold`, `breached` |
| `retrain_job` | Retrain queue and outcomes | `trigger` (schedule / drift / manual), `status`, `scope`, `result` (run, metrics, registry decision) |
| `app_user` | Users | `role` (viewer / engineer / admin), bcrypt `password_hash`, `last_seen_at` |
| `assistant_message` | Assistant turns | `conversation_id`, `role`, `content`, `tools`, `citations`, `flags`, `latency_ms`, `feedback` |

Schema changes go only through Alembic (`platform/wtpdm/db/migrations`). CI runs the
upgrade → downgrade → upgrade round trip.

## MLflow

- **Experiment `wtpdm-health`:** one parent run per farm training, with child runs per
  NBM sensor, detector, component and RUL candidate.
- **Run artifacts:** `evaluation/detector_comparison.csv`, `nbm_comparison.csv`,
  `component_evaluation.csv`, `model_card.md`, plots, and the health bundle.
- **Registered models** `wtpdm-health-{A,B,C}`, with aliases `champion` and `challenger`
  and a `gate` tag on each version (`passed` or the reasons it was held).
