import { getThresholdConfig, putAlert } from "./dynamoClient";
import { publishAlert } from "./snsClient";
import {
  Alert,
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
 * EventBridge-triggered handler (not an AppSync resolver — this service has no
 * GraphQL-facing entrypoint). Evaluates a simple OR-of-thresholds rule: a component
 * breach on EITHER fault probability OR remaining useful life raises an alert,
 * because either signal alone is actionable for maintenance scheduling.
 *
 * "No breach" is the common case and is handled explicitly by returning without
 * writing to DynamoDB or publishing to SNS — silence here is correct behavior, not
 * a missed case.
 */
export async function handler(rawEvent: EventBridgeLikeEvent): Promise<{ alerted: boolean }> {
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
