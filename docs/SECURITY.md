# Security: Wind PdM Platform v2

Security review of the release (phase P7, 2026-10-28): the controls in place, how they are
verified, and the risks that are known and accepted.

## Controls

**Secrets**
- All secrets live in `deploy/compose/.env`: database password, JWT secret, admin password
  and LLM key. The file is git-ignored; `.env.example` holds placeholders only.
- A scan of every tracked file found no keys, tokens or passwords.
- The API refuses to start with a JWT secret shorter than 32 characters.
- The LLM key is never logged. Assistant output is scrubbed of the LLM key, the JWT secret
  and anything shaped like an API key or JWT.

**Authentication**
- OAuth2 password flow issues JWTs: HS256, issuer `wtpdm`, expiry 8 h.
- Passwords are stored as bcrypt hashes. An unknown user is checked against a dummy hash,
  so response timing does not reveal which usernames exist.
- After 5 failed sign-ins in 15 minutes an account is locked (HTTP 429 with `Retry-After`).
- Every sign-in, failure and lockout is audited.
- The user record is re-read on every request, so deactivating a user or changing a role
  takes effect immediately.

**Authorisation**
- Three roles: **viewer** (read), **engineer** (alert workflow), **admin** (users,
  retraining, model approval). Every endpoint declares its minimum role.
- An admin cannot demote or deactivate themselves.
- The assistant's tools are read-only and run with the signed-in user's permissions.
- Tests cover 401, 403 and the role boundaries.

**Input validation**
- Every request body and parameter has a pydantic schema: patterns for farm and turbine ids,
  bounded lengths, enums.
- Time windows and point counts are capped (400 days, 31 days for expected values, 2,000
  points).
- All SQL goes through SQLAlchemy with bound parameters.
- Alert transitions lock the row and return 409 on a stale transition.

**Browser and transport**
- The console is served same-origin and CORS is off by default.
- nginx sends a strict CSP (`script-src 'self'`, no inline scripts, `frame-ancestors 'none'`),
  `X-Frame-Options: DENY`, `nosniff`, a Referrer-Policy and a Permissions-Policy.
- The session token lives in `sessionStorage`, not cookies, so CSRF does not apply.
- The live stream's token travels in the query string. Neither the API nor nginx's stream
  location logs query strings.
- Markdown (model cards, assistant answers) renders without raw HTML.

**Network exposure**
- Only the console (`web`, port 3000) is published on all interfaces.
- The database (5434), MLflow (5001, which has no authentication) and the API (8000) bind
  to `127.0.0.1`.
- TLS is terminated at the edge (reverse proxy or tunnel) when the platform is published.

**Containers**
- The API, worker and retrainer run as a non-root user (uid 10001).
- The console runs on `nginx-unprivileged`.
- Images are pinned; Python and npm dependencies are pinned exactly.

**Assistant**
- Input guardrails: prompt-injection, unsafe-operation (defeating safety functions) and
  off-topic filters; email and phone redaction before text leaves for the provider; 12
  questions per minute per user.
- Output guardrails: grounding check (figures missing from the tool results are marked as
  unverified), secret scrubbing, length cap.
- Every turn is stored for review.

**Audit**
- `audit_log` records sign-ins, alert actions, user administration, model registration,
  promotion and approval, and retrain requests and outcomes.
- The console shows the audit log to engineers and admins.

## Verification
- `platform/tests/test_api.py`: authentication (incl. lockout), RBAC, validation and the
  alert state machine. `test_assistant*.py`: guardrails, grounding and tool specs.
- `frontend/console/scripts/check-no-fake-data.sh` (CI and image build) rejects mock,
  random or fixture data.
- Dependency audits (2026-10-28): `pip-audit` on the platform image, `npm audit` on the
  console. The upgrades in this release cleared 70 of 75 Python advisories and every
  production npm advisory.

## Known and accepted risks

| Risk | Why accepted / mitigation | Follow-up |
|---|---|---|
| MLflow 2.22.4 has advisories fixed only in 3.x (3.15–3.17) | MLflow is reachable only on the internal network and `127.0.0.1`; it holds no user data. A major upgrade migrates the registry and model flavours. | Upgrade to MLflow 3.x and move metadata to Postgres (runbook) |
| pyarrow 19.0.1 advisory (fixed in 23.0.1) | MLflow caps pyarrow below 20 (2.x) or 23 (3.x). The platform reads only Parquet files it wrote itself, never untrusted Arrow data. | Follows the MLflow upgrade |
| setuptools 83.0.0 (fix 84.1.0 is younger than the two-week pinning rule) | Build-time only | Bump at the next dependency refresh |
| Console dev-only tools (vitest, vite dev server, esbuild) have advisories | Not shipped: nginx serves a static build; the dev server is never exposed | Major upgrades of vite/vitest |
| Login lockout and assistant rate limit are in-process | One API replica in this deployment | Move to a shared store (Redis) when scaling out |
| JWTs cannot be revoked before expiry, except by deactivating the user (checked per request) | Expiry is 8 h, and deactivation is immediate | OIDC / refresh tokens if required |
| The LLM provider receives questions and tool results (fleet data, not personal data) | Contact details are redacted; the provider is configurable (any OpenAI-compatible endpoint, including self-hosted) | Choose a provider that meets the data-residency policy |
