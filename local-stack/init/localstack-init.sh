#!/usr/bin/env bash
# One-time setup after `docker compose up -d`: creates the DynamoDB tables and SNS
# topic that alerting-service expects (matching the real naming pattern in
# docs/manual-setup/RUNBOOK.md, with env="local"). Safe to re-run.
set -euo pipefail

ENDPOINT="http://localhost:4566"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

aws_local() {
  aws --endpoint-url="$ENDPOINT" "$@"
}

echo "Waiting for LocalStack..."
until curl -sf "$ENDPOINT/_localstack/health" >/dev/null 2>&1; do sleep 1; done

echo "Creating DynamoDB tables..."
for table in wtb-pdm-local-assets wtb-pdm-local-alerts wtb-pdm-local-config; do
  aws_local dynamodb create-table \
    --table-name "$table" \
    --attribute-definitions AttributeName=id,AttributeType=S \
    --key-schema AttributeName=id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    >/dev/null 2>&1 || echo "  $table already exists, skipping"
done

echo "Creating SNS topic..."
aws_local sns create-topic --name wtb-pdm-local-alerts >/dev/null

echo "Creating S3 buckets (optional - only used if you route pipeline storage through S3 instead of local disk)..."
for bucket in wtb-pdm-local-bronze wtb-pdm-local-silver wtb-pdm-local-gold; do
  aws_local s3api create-bucket --bucket "$bucket" >/dev/null 2>&1 || echo "  $bucket already exists, skipping"
done

echo "Done. Table/topic ARNs for your gateway/.env:"
aws_local dynamodb list-tables
aws_local sns list-topics
