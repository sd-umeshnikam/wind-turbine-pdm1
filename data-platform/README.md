# WTB Data Platform (Databricks Asset Bundle)

Medallion pipeline (bronze -> silver -> gold) plus ML training notebooks for the wind-turbine
predictive-maintenance platform, deployed as a Databricks Asset Bundle.

## Layout

```
data-platform/
  databricks.yml               # bundle root config: dev/staging/uat targets
  resources/jobs.yml            # job/task definitions (medallion pipeline + ML training)
  notebooks/bronze/01_ingest_raw.py           # Auto Loader ingest, per farm, into bronze Delta
  notebooks/silver/02_clean_conform.py        # clean/dedup/event-tag, per farm, into silver.farm_<x>
  notebooks/gold/03_features_and_labels.py    # component features, fault_events, rul_labels
  ml/04_train_fault_classifier.py             # multi-class LightGBM per component
  ml/05_train_rul_regressor.py                # quantile regression (P10/P50/P90) per component
  ml/06_train_trend_forecaster.py             # classical ETS health-index forecaster per asset
```

## Prerequisites

- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/databricks-cli.html) v0.230+ (`databricks bundle` subcommands)
- A configured auth profile, or `DATABRICKS_HOST`/`DATABRICKS_TOKEN` env vars for the target workspace
- Unity Catalog enabled in the target workspace (jobs create catalogs/schemas named after the target: `dev`, `staging`, `uat`)

## Deploy

```bash
databricks bundle validate -t dev
databricks bundle deploy -t dev
```

Swap `-t dev` for `-t staging` or `-t uat` once the corresponding workspace host and credentials
are wired up (see `databricks.yml` placeholders and the root `.github/workflows/databricks-bundle-deploy.yml`).

## Run

```bash
databricks bundle run wtb_medallion_pipeline -t dev
databricks bundle run wtb_ml_training -t dev
```

Both jobs are deployed with `pause_status: PAUSED` on their schedule trigger — unpause once
the bronze S3 prefixes for a target are actually populated, or continue triggering manually.

## Notebook execution order

1. `notebooks/bronze/01_ingest_raw.py` (per farm A/B/C) — Auto Loader stream, append-only
2. `notebooks/silver/02_clean_conform.py` (per farm A/B/C) — depends on that farm's bronze table
3. `notebooks/gold/03_features_and_labels.py` — depends on all three silver tables
4. `ml/04_train_fault_classifier.py`, `ml/05_train_rul_regressor.py`, `ml/06_train_trend_forecaster.py`
   (per component: gearbox/hydraulics/pitch/generator/transformer/rotor_brake/vibration) — depend on
   gold feature/label tables; run independently of the medallion job, typically after a gold refresh

`resources/jobs.yml` encodes steps 1-3 as `wtb_medallion_pipeline` (bronze -> silver -> gold task
dependencies) and steps 4 as `wtb_ml_training`.
