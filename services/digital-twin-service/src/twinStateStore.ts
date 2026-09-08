import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, GetCommand } from "@aws-sdk/lib-dynamodb";
import type { LatestStateItem } from "./types";

let docClient: DynamoDBDocumentClient | undefined;

function getDocClient(): DynamoDBDocumentClient {
  if (!docClient) {
    docClient = DynamoDBDocumentClient.from(new DynamoDBClient({ region: process.env.AWS_REGION }));
  }
  return docClient;
}

/** Reads the latest known per-turbine state (populated by the Timestream/Gold sync
 * path, per ADR-0002 — this service reads it, it does not compute it). Returns
 * `undefined` when no state exists yet for the turbine, e.g. it hasn't reported any
 * telemetry — a legitimate "no data" case, not an error. */
export async function getLatestState(turbineId: string): Promise<LatestStateItem | undefined> {
  const tableName = process.env.TWIN_STATE_TABLE_NAME;
  if (!tableName) {
    throw new Error("TWIN_STATE_TABLE_NAME is not configured.");
  }

  const result = await getDocClient().send(
    new GetCommand({ TableName: tableName, Key: { turbineId } }),
  );

  return result.Item as LatestStateItem | undefined;
}
