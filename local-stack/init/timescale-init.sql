-- Runs automatically on first container start (docker-entrypoint-initdb.d).
-- Substitutes Amazon Timestream for telemetry-api's local backend - see
-- services/telemetry-api/src/postgresClient.ts and pipeline/04_sync_timescale.py.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS sensor_readings (
    turbine_id TEXT NOT NULL,
    time TIMESTAMPTZ NOT NULL,
    sensor TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    unit TEXT
);

SELECT create_hypertable('sensor_readings', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_sensor_readings_turbine_time
    ON sensor_readings (turbine_id, time DESC);
