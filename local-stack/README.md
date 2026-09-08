# local-stack

Everything needed to run the full platform — including the data pipeline and
model training — on a single local Linux box, substituting each managed
AWS/Databricks service with a genuine open-source equivalent.

**Start here: [`docs/LINUX_HOSTING_GUIDE.md`](../docs/LINUX_HOSTING_GUIDE.md)** for
the full step-by-step walkthrough, and [`docs/adr/0004-local-hosting-substitutions.md`](../docs/adr/0004-local-hosting-substitutions.md)
for what each piece substitutes and why.

| Directory | What it is |
|---|---|
| `docker-compose.yml`, `init/`, `up.sh`, `down.sh` | LocalStack (S3/DynamoDB/SNS) + TimescaleDB (Timestream substitute) |
| `pipeline/` | Local port of `data-platform/notebooks/*` and `data-platform/ml/*` — plain PySpark + Delta Lake, real model training |
| `inference/` | FastAPI server substituting Databricks Model Serving, loads the real models the pipeline trained |
| `gateway/` | Node/Apollo Server substituting AppSync — serves the real `schema.graphql` unchanged, resolvers call `services/*/src` handlers in-process |
| `nginx/` | Config serving the built frontend + proxying `/graphql` to the gateway |
| `systemd/` | Unit files for persisting the gateway + inference server across reboots |
