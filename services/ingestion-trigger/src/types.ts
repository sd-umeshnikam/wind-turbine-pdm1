/**
 * Bronze landing path is `s3://<env>-wtb-bronze/farm=A|B|C/turbine=<asset_id>/...`
 * (see docs/architecture/BLUEPRINT.md section 3). This pattern is the defensive
 * check inside the handler even though the S3 bucket notification itself should
 * already be scoped to this prefix — belt-and-suspenders against a misconfigured
 * notification rule silently triggering jobs on unrelated objects.
 */
export const BRONZE_KEY_PATTERN = /^farm=[ABC]\/turbine=[^/]+\/.+$/;

export interface S3RecordLike {
  eventName?: string;
  s3?: {
    bucket?: { name?: string };
    object?: { key?: string };
  };
}

export interface S3EventLike {
  Records?: S3RecordLike[];
}

export interface TriggerResult {
  bucket: string;
  key: string;
  runId?: number;
  skipped?: boolean;
  reason?: string;
}

export class ValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ValidationError";
  }
}

export class UpstreamError extends Error {
  constructor(message: string, readonly cause?: unknown) {
    super(message);
    this.name = "UpstreamError";
  }
}
