# One image for every Python service (api, worker, replay, assistant, jobs); the
# compose `command` picks the role. Code is copied in (not bind-mounted) so images
# are reproducible; `deploy/compose/docker-compose.dev.yml` mounts source for development.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY pyproject.toml ./
# Install dependencies first (cached layer), then the package itself.
RUN pip install --upgrade pip==26.2 setuptools==83.0.0 \
    && mkdir wtpdm && touch wtpdm/__init__.py && pip install ".[dev]" && rm -rf wtpdm

COPY wtpdm ./wtpdm
COPY tests ./tests
RUN pip install --no-deps .

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/lake /mlartifacts && chown -R app:app /data /mlartifacts
# Named volumes mounted here inherit this ownership on first use.
USER app

EXPOSE 8000
# uvicorn's access log prints query strings (the stream token); the app logs each request
# itself, path only.
CMD ["uvicorn", "wtpdm.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
