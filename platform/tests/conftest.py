import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from wtpdm.settings import get_settings

# The API refuses weak secrets; tests sign their own tokens when none is configured.
os.environ.setdefault("WTPDM_JWT_SECRET", "pytest-only-secret-" + "x" * 32)


@pytest.fixture(scope="session")
def db_engine():
    """Engine for integration tests; skips them when the compose database isn't reachable."""
    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("database not reachable (start deploy/compose `db` + `migrate`)")
    return engine
