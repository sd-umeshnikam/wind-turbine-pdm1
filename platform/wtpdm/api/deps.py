"""Request-scoped dependencies shared by the routers."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from wtpdm.db.session import _session_factory


def db() -> Iterator[Session]:
    """One session per request: committed when the endpoint returns, rolled back on error."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
