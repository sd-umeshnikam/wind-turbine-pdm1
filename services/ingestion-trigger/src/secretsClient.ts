import { SecretsManagerClient, GetSecretValueCommand } from "@aws-sdk/client-secrets-manager";

let client: SecretsManagerClient | undefined;
// Cached for the lifetime of the execution environment (warm-start reuse) — Secrets
// Manager is read once per cold start, not once per S3 event.
let cachedToken: string | undefined;

function getClient(): SecretsManagerClient {
  if (!client) {
    client = new SecretsManagerClient({ region: process.env.AWS_REGION });
  }
  return client;
}

/** Fetches the Databricks Jobs API auth token from Secrets Manager. The secret is
 * expected to hold the token as a plain string (`SecretString`), not JSON — swap the
 * parse logic here if the secret is stored as `{"token": "..."}` instead. */
export async function getDatabricksAuthToken(): Promise<string> {
  if (cachedToken) return cachedToken;

  const secretId = process.env.DATABRICKS_TOKEN_SECRET_ID;
  if (!secretId) {
    throw new Error("DATABRICKS_TOKEN_SECRET_ID is not configured.");
  }

  const result = await getClient().send(new GetSecretValueCommand({ SecretId: secretId }));
  if (!result.SecretString) {
    throw new Error(`Secret ${secretId} has no SecretString value.`);
  }

  cachedToken = result.SecretString;
  return cachedToken;
}
