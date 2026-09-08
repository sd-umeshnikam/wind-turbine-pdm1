import { getThresholdConfig, listActiveAlerts, putAlert } from "./dynamoClient";
import { publishAlert } from "./snsClient";
import {
  Alert,
  AlertingLambdaEvent,
  AlertSeverity,
  EventBridgeLikeEvent,
  PredictionEventDetail,
  UpstreamError,
  ValidationError,
} from "./types";

function parseDetail(rawEvent: EventBridgeLikeEvent): PredictionEventDetail {
  const detail = rawEvent?.detail;
  if (typeof detail !== "object" || detail === null) {
    throw new ValidationError("Event is missing a `detail` payload.");
  }
  const d = detail as Record<string, unknown>;

  if (typeof d.turbineId !== "string" || d.turbineId.length === 0) {
    throw new ValidationError("detail.turbineId is required.");
  }
  if (typeof d.component !== "string" || d.component.length === 0) {
    throw new ValidationError("detail.component is required.");
  }
  if (typeof d.faultProbability !== "number" || Number.isNaN(d.faultProbability)) {
    throw new ValidationError("detail.faultProbability must be a number.");
  }
  if (typeof d.rulHoursP50 !== "number" || Number.isNaN(d.rulHoursP50)) {
    throw new ValidationError("detail.rulHoursP50 must be a number.");
  }

  return {
    turbineId: d.turbineId,
    component: d.component,
    faultProbability: d.faultProbability,
    rulHoursP50: d.rulHoursP50,
  };
}

function severityFor(detail: PredictionEventDetail): AlertSeverity {
  if (detail.faultProbability > 0.9 || detail.rulHoursP50 < 24) return "critical";
  if (detail.faultProbability > 0.8 || detail.rulHoursP50 < 48) return "high";
  return "medium";
}

/**
 * EventBridge-triggered write path. Evaluates a simple OR-of-thresholds rule: a
 * component breach on EITHER fault probability OR remaining useful life raises an
 * alert, because either signal alone is actionable for maintenance scheduling.
 *
 * "No breach" is the common case and is handled explicitly by returning without
 * writing to DynamoDB or publishing to SNS — silence here is correct behavior, not
 * a missed case.
 */
async function evaluateAndAlert(rawEvent: EventBridgeLikeEvent): Promise<{ alerted: boolean }> {
  const detail = parseDetail(rawEvent);

  let thresholds;
  try {
    thresholds = await getThresholdConfig(detail.component);
  } catch (err) {
    console.error("Failed to load threshold config", { component: detail.component, err });
    throw new UpstreamError("Failed to load alert threshold configuration.", err);
  }

  const breached =
    detail.faultProbability > thresholds.faultProbabilityThreshold ||
    detail.rulHoursP50 < thresholds.rulHoursP50Threshold;

  if (!breached) {
    return { alerted: false };
  }

  const alert: Alert = {
    id: `${detail.turbineId}#${detail.component}`,
    turbineId: detail.turbineId,
    component: detail.component,
    severity: severityFor(detail),
    message: `${detail.component} on ${detail.turbineId}: faultProbability=${detail.faultProbability.toFixed(
      2,
    )}, rulHoursP50=${detail.rulHoursP50.toFixed(1)}`,
    createdAt: new Date().toISOString(),
    acknowledged: false,
  };
  // Keyed by turbine+component (see dynamoClient.putAlert) so a repeat breach
  // updates the same alert item instead of accumulating duplicates.

  try {
    await putAlert(alert);
    await publishAlert(alert);
  } catch (err) {
    console.error("Failed to persist/publish alert", { alert, err });
    throw new UpstreamError("Failed to write or publish the alert.", err);
  }

  return { alerted: true };
}

/**
 * Backs `Query.activeAlerts` (see infra/terraform/modules/appsync-api/main.tf's
 * `field_to_service` map, which invokes this same Lambda for that query field).
 */
async function readActiveAlerts(): Promise<Alert[]> {
  try {
    return await listActiveAlerts();
  } catch (err) {
    console.error("Failed to list active alerts", err);
    throw new UpstreamError("Failed to read active alerts.", err);
  }
}

/**
 * Two real entrypoints on one Lambda, dispatched by event shape:
 *  - AppSync direct Lambda data source event (`{field, arguments}` - see
 *    templates/invoke_request.vtl) -> read path, `Query.activeAlerts`.
 *  - EventBridge event (`{detail, ...}`) -> write path, evaluate-and-alert.
 * This is the fix for a real gap: main.tf already wires activeAlerts to this
 * service, but until now nothing here could actually answer that call.
 */
export async function handler(
  rawEvent: AlertingLambdaEvent,
): Promise<{ alerted: boolean } | Alert[]> {
  if ("field" in rawEvent) {
    return readActiveAlerts();
  }
  return evaluateAndAlert(rawEvent);
}
