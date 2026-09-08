# alerting-service

Evaluates a new prediction/Gold-data event against configurable thresholds and raises
an alert (DynamoDB + SNS) when breached. Follows `telemetry-api`'s file layout; see
that service's README for the shared conventions.

## What it does

Unlike the other services, this is **not** an AppSync resolver — it is triggered by an
**EventBridge rule** on new prediction/Gold data (per BLUEPRINT.md section 5), so it
has no GraphQL-facing entrypoint. `src/handler.ts`:

1. Validates the EventBridge event's `detail` payload (`turbineId`, `component`,
   `faultProbability`, `rulHoursP50`).
2. Reads per-component thresholds from DynamoDB (`src/dynamoClient.ts`), falling back
   to defaults (`faultProbability > 0.7` or `rulHoursP50 < 72`) when no config item
   exists yet for that component.
3. If breached (either condition, evaluated with OR — either signal alone is
   actionable): upserts an alert item into DynamoDB, keyed by `turbineId#component`
   so a repeat breach refreshes the alert instead of duplicating it, then publishes to
   an SNS topic.
4. If not breached: returns `{ alerted: false }` without any AWS write — this is the
   common case and is handled explicitly, not treated as an error path.

**No data vs. broken:** a missing/malformed `detail` payload throws a validation
error before any AWS call; a DynamoDB or SNS failure is caught, logged, and re-thrown
as an upstream error so the EventBridge invocation is recorded as failed (and can be
retried/DLQ'd by the rule's retry policy) rather than silently swallowed.

## IAM permissions needed

- `dynamodb:GetItem` on the alert-config table ARN
- `dynamodb:PutItem` on the alerts table ARN
- `sns:Publish` on the alerts topic ARN

All three scoped to the specific table/topic ARNs, not `*`.

## Environment variables

| Variable | Purpose |
|---|---|
| `ALERT_CONFIG_TABLE_NAME` | DynamoDB table holding per-component threshold overrides |
| `ALERTS_TABLE_NAME` | DynamoDB table holding current alert state |
| `ALERTS_TOPIC_ARN` | SNS topic alerts are published to |

## Running locally

```bash
npm install
npm test
npm run build
npm run typecheck
```

## Assumptions

- The EventBridge event `detail` shape (`turbineId`, `component`, `faultProbability`,
  `rulHoursP50`) is assumed — no EventBridge schema registry entry existed at
  scaffold time. Reconcile against whatever `prediction-api` / the Gold-sync job
  actually emits.
- Work-order integration (RDS Postgres, per BLUEPRINT.md's backing-store row for this
  service) is out of scope for this scaffold pass — this handler only writes the
  DynamoDB alert state and SNS notification described in the task. Wiring RDS
  work-order creation is a follow-up, not implemented here.
