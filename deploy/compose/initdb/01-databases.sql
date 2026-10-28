-- Reserved for moving the MLflow store to Postgres (see docs/RUNBOOK.md); MLflow currently
-- keeps its metadata in a file store on the `mlruns` volume. The platform schema lives in `wtpdm`.
CREATE DATABASE mlflow OWNER wtpdm;
\c wtpdm
CREATE EXTENSION IF NOT EXISTS timescaledb;
