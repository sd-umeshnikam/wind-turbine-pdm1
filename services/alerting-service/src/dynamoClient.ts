import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, GetCommand, PutCommand, ScanCommand } from "@aws-sdk/lib-dynamodb";
import { Alert, AlertThresholdConfig, DEFAULT_THRESHOLDS } from "./types";
import type { ComponentType } from "../../shared/types";

let docClient: DynamoDBDocumentClient | undefined;

function getDocClient(): DynamoDBDocumentClient {
  if (!docClient) {
    docClient = DynamoDBDocumentClient.from(new DynamoDBClient({ region: process.env.AWS_REGION }));
  }
  return docClient;
}

/** Reads the per-component alert threshold config, falling back to defaults for a
 * component that has no override row yet (so alerting works before ops configures
 * anything). */
export async function getThresholdConfig(component: ComponentType): Promise<AlertThresholdConfig> {
  const tableName = process.env.ALERT_CONFIG_TABLE_NAME;
  if (!tableName) {
    throw new Error("ALERT_CONFIG_TABLE_NAME is not configured.");
  }

  const result = await getDocClient().send(
    new GetCommand({ TableName: tableName, Key: { component } }),
  );

  if (!result.Item) {
    return { component, ...DEFAULT_THRESHOLDS };
  }

  return {
    component,
    faultProbabilityThreshold:
      result.Item.faultProbabilityThreshold ?? DEFAULT_THRESHOLDS.faultProbabilityThreshold,
    rulHoursP50Threshold:
      result.Item.rulHoursP50Threshold ?? DEFAULT_THRESHOLDS.rulHoursP50Threshold,
  };
}

/** Upserts the alert item, keyed by (turbineId, component) so a repeat breach
 * refreshes the same alert rather than creating duplicates. */
export async function putAlert(alert: Alert): Promise<void> {
  const tableName = process.env.ALERTS_TABLE_NAME;
  if (!tableName) {
    throw new Error("ALERTS_TABLE_NAME is not configured.");
  }

  await getDocClient().send(new PutCommand({ TableName: tableName, Item: alert }));
}

/**
 * Backs `Query.activeAlerts`. A `Scan` is fine at this table's expected size (one
 * item per turbine+component breach, not per reading) - if that assumption stops
 * holding, add a GSI on `acknowledged` rather than paginating an unbounded Scan.
 */
export async function listActiveAlerts(): Promise<Alert[]> {
  const tableName = process.env.ALERTS_TABLE_NAME;
  if (!tableName) {
    throw new Error("ALERTS_TABLE_NAME is not configured.");
  }

  const result = await getDocClient().send(
    new ScanCommand({
      TableName: tableName,
      FilterExpression: "acknowledged = :false",
      ExpressionAttributeValues: { ":false": false },
    }),
  );

  return (result.Items ?? []) as Alert[];
}
