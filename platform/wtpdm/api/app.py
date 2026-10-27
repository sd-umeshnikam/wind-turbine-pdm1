"""Platform API entry point. Routers are added per phase (P4)."""

from fastapi import FastAPI
from sqlalchemy import text

from wtpdm import __version__
from wtpdm.db.session import get_engine
from wtpdm.logging import configure_logging
from wtpdm.settings import get_settings

configure_logging(get_settings().log_level)

app = FastAPI(
    title="Wind Turbine PdM Platform API",
    version=__version__,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


@app.get("/api/health", tags=["ops"])
def health() -> dict:
    """Liveness: the process is up."""
    return {"status": "ok", "version": __version__}


@app.get("/api/ready", tags=["ops"])
def ready() -> dict:
    """Readiness: dependencies reachable."""
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ready"}
