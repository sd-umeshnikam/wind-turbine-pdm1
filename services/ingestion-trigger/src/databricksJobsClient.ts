export interface RunJobParams {
  bucket: string;
  key: string;
  authToken: string;
}

/** Triggers a Databricks Jobs "run now" for the bronze->silver->gold workflow,
 * passing the landed object's location as notebook parameters so the job can scope
 * its Auto Loader / MERGE step to (at minimum) the new file's farm/turbine. */
export async function triggerJobRun(params: RunJobParams): Promise<number> {
  const host = process.env.DATABRICKS_HOST;
  const jobId = process.env.DATABRICKS_JOB_ID;
  if (!host || !jobId) {
    throw new Error("DATABRICKS_HOST / DATABRICKS_JOB_ID are not configured.");
  }

  const url = `${host.replace(/\/$/, "")}/api/2.1/jobs/run-now`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${params.authToken}`,
    },
    body: JSON.stringify({
      job_id: Number(jobId),
      notebook_params: {
        bronze_bucket: params.bucket,
        bronze_key: params.key,
      },
    }),
  });

  if (!response.ok) {
    throw new Error(`Databricks Jobs API returned HTTP ${response.status}`);
  }

  const body = (await response.json()) as { run_id?: number };
  if (typeof body.run_id !== "number") {
    throw new Error("Databricks Jobs API response did not include a run_id.");
  }
  return body.run_id;
}
