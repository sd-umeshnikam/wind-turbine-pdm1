# digital-twin-service

Publishes near-real-time per-turbine state (pitch angle, rotor speed, per-component
health) to the AppSync `onTwinUpdate(turbineId)` subscription channel, for the 3D
digital-twin view (see ADR-0003 for what this "twin" is/is not scoped to). Follows
`telemetry-api`'s file layout; see that service's README for shared conventions.

## What it does

Triggered by **EventBridge** (not AppSync) — either a "new telemetry landed for this
turbine" event pattern, or a schedule. `src/handler.ts`:

1. Validates the event's `detail.turbineId`.
2. Reads the turbine's latest known state from DynamoDB (`src/twinStateStore.ts` —
   populated by the Timestream/Gold sync path per ADR-0002; this service only reads
   it, it does not compute health scores itself).
3. If no state exists yet (turbine has never reported) → returns
   `{ published: false }` without calling AppSync — a legitimate no-data case.
4. Otherwise maps it to `TwinState` and publishes via `src/appsyncClient.ts`.
5. A DynamoDB or AppSync failure is caught, logged, and re-thrown as an upstream
   error rather than swallowed.

## How it publishes to `onTwinUpdate` (decision + alternative)

**Chosen: the mutation-trigger pattern.** The schema is expected to expose a
`Mutation.publishTwinUpdate(input: TwinStateInput!): TwinState` field wired to a
*local* (no-op passthrough) resolver decorated `@aws_subscribe(["onTwinUpdate"])`.
`src/appsyncClient.ts` calls this mutation over AppSync's HTTP GraphQL endpoint,
SigV4-signed with the Lambda's execution role (via the lightweight `aws4fetch`
library — no full AWS SDK GraphQL client exists for this).

**Why not an AppSync JS resolver directly:** a JS resolver only runs in response to
an *incoming* AppSync request (a query/mutation/subscription the client initiates) —
it has no mechanism to originate a push driven by an external event. Since the state
this service publishes originates from an EventBridge-triggered Lambda reading
DynamoDB (i.e., outside any AppSync request), there is no incoming request for a JS
resolver to attach to. The mutation-trigger pattern is AWS's documented way to drive
a subscription from an external event source, so it's the only one of the two options
that actually fits this trigger shape.

## IAM permissions needed

- `dynamodb:GetItem` on the twin-state table ARN
- `appsync:GraphQL` scoped to the specific AppSync API ARN's `Mutation.publishTwinUpdate`
  field, for the SigV4-signed HTTP call

## Environment variables

| Variable | Purpose |
|---|---|
| `TWIN_STATE_TABLE_NAME` | DynamoDB table holding latest per-turbine state |
| `APPSYNC_GRAPHQL_URL` | AppSync API's GraphQL HTTP endpoint |
| `AWS_REGION` | Used both for the DynamoDB client and to sign the AppSync request |

## Running locally

```bash
npm install
npm test
npm run build
npm run typecheck
```

## Assumptions

- `schema.graphql` did not exist at scaffold time. `Mutation.publishTwinUpdate` and
  `TwinStateInput` are assumed names — reconcile against the real schema once
  the AppSync workstream lands it; this is the one field this scaffold needs the
  schema author to add (query/subscription fields the task described are otherwise
  used as-is).
- This scaffold implements the single-turbine-per-invocation path (triggered by a
  per-turbine EventBridge event). A schedule-driven full-fleet sweep would loop this
  same per-turbine logic across all turbine IDs — not implemented here to keep the
  stub genuinely thin, but the core `handler` function composes directly into that
  loop without change.
