FROM python:3.12-slim

RUN pip install --no-cache-dir --upgrade pip

COPY requirements-dev.txt requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt

WORKDIR /workspace/wind-turbine-pdm-platform/local-stack/chatbot

EXPOSE 8090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
