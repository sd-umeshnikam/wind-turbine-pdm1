import pytest
from sqlalchemy import inspect, text

from wtpdm.db.models import Base

EXPECTED_TABLES = {
    "farm",
    "turbine",
    "component",
    "subcomponent",
    "sensor",
    "event",
    "telemetry",
    "health_score",
    "alert",
    "alert_note",
    "audit_log",
    "assistant_message",
    "replay_state",
    "model_deployment",
    "drift_report",
    "retrain_job",
    "app_user",
}


def test_metadata_declares_every_table():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_turbine_key_includes_farm():
    # Raw asset ids repeat across farms; the (farm, asset) pair must be unique, not asset alone.
    uniques = [
        c for c in Base.metadata.tables["turbine"].constraints if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert any({col.name for col in u.columns} == {"farm_id", "asset_id"} for u in uniques)


@pytest.mark.integration
def test_migration_created_schema_and_hypertables(db_engine):
    assert set(inspect(db_engine).get_table_names()) >= EXPECTED_TABLES
    with db_engine.connect() as conn:
        hypertables = {
            r[0]
            for r in conn.execute(text("SELECT hypertable_name FROM timescaledb_information.hypertables"))
        }
    assert {"telemetry", "health_score"} <= hypertables
