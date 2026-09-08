import { getDatabricksAuthToken } from "./secretsClient";
import { triggerJobRun } from "./databricksJobsClient";
import { BRONZE_KEY_PATTERN, S3EventLike, TriggerResult, UpstreamError, ValidationError } from "./types";

function extractObjects(event: S3EventLike): Array<{ bucket: string; key: string }> {
  if (!event || !Array.isArray(event.Records) || event.Records.length === 0) {
    throw new ValidationError("Event has no S3 Records.");
  }

  return event.Records.map((record) => {
    const bucket = record.s3?.bucket?.name;
    const key = record.s3?.object?.key;
    if (!bucket || !key) {
      throw new ValidationError("An S3 record is missing bucket name or object key.");
    }
    // S3 event keys are URL-encoded (spaces as '+'), same as the SDK expects raw.
    return { bucket, key: decodeURIComponent(key.replace(/\+/g, " ")) };
  });
}

/**
 * S3 `ObjectCreated`-triggered handler. Kicks off the Databricks bronze->silver->gold
 * workflow run for each newly landed object. Processes every record in the batch
 * independently (one bad/irrelevant key shouldn't block triggering the rest), and
 * reports skipped-vs-triggered explicitly rather than silently dropping non-matching
 * keys.
 */
export async function handler(rawEvent: S3EventLike): Promise<TriggerResult[]> {
  const objects = extractObjects(rawEvent);

  let authToken: string;
  try {
    authToken = await getDatabricksAuthToken();
  } catch (err) {
    console.error("Failed to load Databricks auth token", err);
    throw new UpstreamError("Failed to load Databricks auth token.", err);
  }

  const results: TriggerResult[] = [];
  const failures: Array<{ bucket: string; key: string; err: unknown }> = [];

  for (const { bucket, key } of objects) {
    if (!BRONZE_KEY_PATTERN.test(key)) {
      results.push({ bucket, key, skipped: true, reason: "key does not match bronze prefix pattern" });
      continue;
    }

    try {
      const runId = await triggerJobRun({ bucket, key, authToken });
      results.push({ bucket, key, runId });
    } catch (err) {
      console.error("Failed to trigger Databricks job run", { bucket, key, err });
      failures.push({ bucket, key, err });
    }
  }

  if (failures.length > 0) {
    throw new UpstreamError(
      `Failed to trigger Databricks job run for ${failures.length}/${objects.length} object(s).`,
      failures,
    );
  }

  return results;
}
