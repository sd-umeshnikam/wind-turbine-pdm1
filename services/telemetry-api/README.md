# telemetry-api

Serves current and historical turbine sensor readings from Amazon Timestream. This is
the reference implementation for the backend — every other service under
`services/` (`prediction-api`, `alerting-service`, `digital-twin-service`,
`ingestion-trigger`) follows this same file layout and testing approach:

```
package.json        # own deployable unit — own deps, own build, own test run
tsconfig.json
src/handler.ts       # Lambda entrypoint
src/<name>Client.ts   # thin wrapper around the one external system this service calls
src/types.ts          # local types + re-exports from services/shared/types.ts
test/handler.test.ts  # unit tests, upstream client mocked
README.md
```

## What it does

Implements the `Query.telemetry(turbineId, from, to): [SensorReading]` resolver from
the AppSync schema. It is invoked as an **AppSync direct Lambda data source** — not a
public HTTP endpoint. AppSync calls this Lambda's `handler` export with an event whose
`arguments` field carries the resolved GraphQL arguments; the Lambda's return value (or
thrown error) becomes the field's GraphQL result (or GraphQL error).

Flow: validate input → build a Timestream query → run it via
`src/timestreamClient.ts` → map rows to `SensorReading[]`.

**No data vs. broken, handled explicitly:**
- Valid turbine/time range with no rows → returns `[]` (not an error).
- Missing/invalid `turbineId`, `from`, or `to` → throws a validation error before any
  Timestream call is made.
- Timestream call fails (throttling, permissions, etc.) → caught, logged server-side,
  re-thrown as a generic upstream error so AppSync surfaces a clean GraphQL error
  without leaking internal exception details to the client.

**On query parameterization:** Amazon Timestream's Query API has no bind-parameter
mechanism comparable to a prepared statement — the query is always a single string.
Since we can't parameterize our way out of injection, `src/handler.ts` defends with
strict allow-list validation instead: `turbineId` must match `^[A-Za-z0-9_-]{1,64}$`,
and `from`/`to` are only accepted if they parse as real dates — and the value actually
interpolated into the query string is the re-serialized `Date`, never the raw input.

**Assumption:** `infra/terraform/modules/appsync-api/schema.graphql` did not exist yet
when this service was scaffolded, so the `SensorReading` shape and resolver signature
follow the schema shape given in the scaffolding task (mirrored in
`services/shared/types.ts`). Reconcile against the real schema file once it lands.
Also assumed: the Timestream table stores one row per `(turbine_id, time,
measure_name)` with the value in `measure_value::double` and a `unit` dimension/column
— adjust `buildQuery`/`mapRowsToReadings` in `src/handler.ts` if the actual table
schema differs.

## IAM permissions needed

Scoped to the specific Timestream database/table, not `*`:

- `timestream:Select` on the specific table ARN
  (`arn:aws:timestream:<region>:<account>:database/<db>/table/<table>`)
- `timestream:DescribeEndpoints` — required with `Resource: "*"` because Timestream's
  Query API always requires an initial endpoint-discovery call, and that call isn't
  scopeable to a single resource; the AWS SDK v3 Timestream Query client issues this
  automatically before the first `Select`.

No other AWS permissions are required by this function.

## Environment variables

| Variable | Purpose |
|---|---|
| `TIMESTREAM_DATABASE_NAME` | Timestream database to query |
| `TIMESTREAM_TABLE_NAME` | Timestream table to query |
| `AWS_REGION` | Standard Lambda-provided region variable, used to construct the SDK client |

## Running locally

```bash
npm install
npm test        # runs vitest; Timestream is mocked, no AWS credentials needed
npm run build    # bundles src/handler.ts -> dist/handler.js via esbuild
npm run typecheck
```

## Deployment

Built independently of the other four services (see
`.github/workflows/backend-deploy.yml`) — a change here never requires redeploying
`prediction-api`, `alerting-service`, `digital-twin-service`, or `ingestion-trigger`.
