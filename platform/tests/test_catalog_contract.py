"""Data contract for the loaded catalog: the published facts of the CARE dataset.
Integration tests - they run against the compose database after ingest + load_db."""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

EXPECTED = {
    # farm: (turbines, anomaly events, normal events, curated rows)
    "A": (5, 11, 11, 1_196_747),
    "B": (9, 6, 9, 859_065),
    "C": (22, 27, 31, 3_187_136),
}


@pytest.fixture(scope="module")
def loaded(db_engine):
    with db_engine.connect() as conn:
        if not conn.execute(text("SELECT count(*) FROM event")).scalar():
            pytest.skip("catalog not loaded (run wtpdm.ingest.pipeline / load_db)")
    return db_engine


def test_counts_match_published_dataset(loaded):
    with loaded.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT f.id,
                       (SELECT count(*) FROM turbine t WHERE t.farm_id = f.id),
                       count(*) FILTER (WHERE e.label = 'anomaly'),
                       count(*) FILTER (WHERE e.label = 'normal'),
                       sum(e.n_rows)
                FROM farm f JOIN event e ON e.farm_id = f.id GROUP BY f.id ORDER BY f.id
                """
            )
        ).all()
    assert {r[0]: tuple(r[1:]) for r in rows} == EXPECTED


def test_every_event_belongs_to_one_turbine_of_its_own_farm(loaded):
    with loaded.connect() as conn:
        bad = conn.execute(
            text(
                "SELECT count(*) FROM event e JOIN turbine t ON t.id = e.turbine_id "
                "WHERE t.farm_id <> e.farm_id"
            )
        ).scalar()
    assert bad == 0


def test_prediction_window_precedes_event_end(loaded):
    with loaded.connect() as conn:
        bad = conn.execute(
            text(
                "SELECT count(*) FROM event "
                "WHERE NOT (window_start <= prediction_start AND prediction_start <= event_end)"
            )
        ).scalar()
    assert bad == 0


def test_every_farm_has_required_conditions_and_monitored_sensors(loaded):
    with loaded.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT farm_id,
                       count(*) FILTER (WHERE role = 'monitored'),
                       array_agg(DISTINCT condition_kind) FILTER (WHERE role = 'condition')
                FROM sensor GROUP BY farm_id
                """
            )
        ).all()
    for _farm, monitored, kinds in rows:
        assert monitored > 0
        assert {"power", "wind_speed", "ambient_temp"} <= set(kinds)
