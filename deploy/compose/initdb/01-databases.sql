-- Separate database for the MLflow tracking/registry store; the platform schema lives in `wtpdm`.
CREATE DATABASE mlflow OWNER wtpdm;
\c wtpdm
CREATE EXTENSION IF NOT EXISTS timescaledb;
