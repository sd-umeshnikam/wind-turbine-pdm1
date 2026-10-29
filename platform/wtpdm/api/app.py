"""Platform API entry point: REST + server-sent events over the platform database, the
curated lake and the MLflow registry. OpenAPI at /api/docs.

Startup refuses to run without a strong JWT secret and seeds the first admin from
WTPDM_ADMIN_USERNAME / WTPDM_ADMIN_PASSWORD when no admin exists yet.
"""

from __future__ import annotations

import threading
import time
import uuid
from contextlib import asynccontextmanager

import mlflow
import structlog
from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mlflow.exceptions import MlflowException
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from wtpdm import __version__, catalog
from wtpdm.api import models_service
from wtpdm.api.routers import alerts, assistant, auth, data, fleet, mlops, stream, turbines
from wtpdm.api.security import Principal, hash_password, jwt_secret, viewer
from wtpdm.db.models import AppUser, AuditLog, Role
from wtpdm.db.session import get_engine, session_scope
from wtpdm.logging import configure_logging, get_logger
from wtpdm.settings import get_settings

configure_logging(get_settings().log_level)
log = get_logger("api")


def seed_admin() -> bool:
    """Create the first admin from the environment when none exists. Returns whether one was created."""
    settings = get_settings()
    password = settings.admin_password.get_secret_value()
    with session_scope() as s:
        if s.scalars(select(AppUser).where(AppUser.role == Role.ADMIN)).first():
            return False
        if len(password) < 12:
            log.warning("no admin user and WTPDM_ADMIN_PASSWORD is unset or shorter than 12 characters")
            return False
        username = settings.admin_username.strip().lower()
        s.add(
            AppUser(
                username=username,
                display_name="Platform administrator",
                password_hash=hash_password(password),
                role=Role.ADMIN,
                is_active=True,
            )
        )
        s.add(AuditLog(actor="system:api", action="user.seed_admin", entity="user", entity_id=username))
    log.info("seeded admin user", username=username)
    return True


def warm_champions() -> None:
    """Load each farm's champion bundle in the background so the first expected-value
    request does not wait for the download (several seconds for farm C)."""
    for farm in catalog.available_farms(get_settings().lake_root):
        try:
            models_service.champion(farm)
        except Exception as exc:  # the request path reports the same failure properly
            log.warning("champion warm-up failed", farm=farm, error=str(exc)[:200])


@asynccontextmanager
async def lifespan(_: FastAPI):
    jwt_secret()  # fail fast on a missing or weak JWT secret
    mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)
    seed_admin()
    threading.Thread(target=warm_champions, name="warm-champions", daemon=True).start()
    yield


app = FastAPI(
    title="Wind Turbine PdM Platform API",
    version=__version__,
    description=(
        "Fleet health, sub-part condition, alerts work queue, model operations and drift for the "
        "CARE wind-farm dataset. Live data is a replay of recorded SCADA history; each turbine "
        "runs on its own (anonymised) data clock. Authenticate with `POST /api/auth/token`."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

if get_settings().cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Request id (honoured from X-Request-ID or generated), access log, timing."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    structlog.contextvars.bind_contextvars(request_id=request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.unbind_contextvars("request_id")
    response.headers["X-Request-ID"] = request_id
    if request.url.path not in ("/api/health", "/api/ready"):
        log.info(
            "request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,  # never the query string: it can carry the stream token
            status=response.status_code,
            ms=round((time.perf_counter() - start) * 1000, 1),
            user=getattr(request.state, "user", None),
        )
    return response


@app.exception_handler(MlflowException)
async def mlflow_unavailable(request: Request, exc: MlflowException):
    log.warning("model registry error", path=request.url.path, error=str(exc)[:300])
    return JSONResponse(
        status_code=503, content={"detail": "Model registry unavailable or returned an error"}
    )


for module in (auth, fleet, turbines, alerts, mlops, data, stream, assistant):
    app.include_router(module.router, prefix="/api")


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


class ClientError(BaseModel):
    message: str = Field(max_length=500)
    stack: str = Field("", max_length=4000)
    path: str = Field("", max_length=300)
    user_agent: str = Field("", max_length=300)


@app.post("/api/client-errors", status_code=status.HTTP_204_NO_CONTENT, tags=["ops"])
def client_error(body: ClientError, user: Principal = Depends(viewer)) -> Response:
    """A crash in the console, reported by the browser so it shows up in the api logs."""
    log.warning(
        "console error",
        user=user.username,
        message=body.message,
        stack=body.stack,
        path=body.path,
        user_agent=body.user_agent,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
