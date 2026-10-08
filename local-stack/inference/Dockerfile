# Unlike pipeline/Dockerfile, serve.py reads Delta tables via the native
# `deltalake` (Rust) library, not PySpark - no JDK needed here at all.
FROM python:3.12-slim

# lightgbm's compiled core needs the GNU OpenMP runtime, which python:3.12-slim
# doesn't include (same fix as pipeline/Dockerfile needed).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /workspace/wind-turbine-pdm-platform/local-stack/inference

EXPOSE 8080
CMD ["uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "8080"]
