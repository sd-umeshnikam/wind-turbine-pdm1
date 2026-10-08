# Java 17 (JAVA_HOME preset by the base image) + Python, for run_pipeline.sh's
# PySpark/Delta steps. Requirements are installed here for layer caching; the repo
# itself is bind-mounted at runtime (see ../docker-compose.yml's `pipeline` service)
# so code/dataset changes don't require a rebuild.
FROM eclipse-temurin:17-jdk-jammy

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python-is-python3 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /workspace/wind-turbine-pdm-platform/local-stack/pipeline
