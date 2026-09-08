import { getLatestState } from "./twinStateStore";
import { publishTwinUpdate } from "./appsyncClient";
import {
  EventBridgeLikeEvent,
  TwinTriggerEventDetail,
  TwinState,
  UpstreamError,
  ValidationError,
} from "./types";

const TURBINE_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

function parseDetail(rawEvent: EventBridgeLikeEvent): TwinTriggerEventDetail {
  const detail = rawEvent?.detail;
  if (typeof detail !== "object" || detail === null) {
    throw new ValidationError("Event is missing a `detail` payload.");
  }
  const d = detail as Record<string, unknown>;
  if (typeof d.turbineId !== "string" || !TURBINE_ID_PATTERN.test(d.turbineId)) {
    throw new ValidationError("detail.turbineId is required and must be a valid identifier.");
  }
  return { turbineId: d.turbineId };
}

/**
 * EventBridge-triggered handler (schedule, or "new telemetry landed" pattern — see
 * README) that republishes one turbine's latest state to the `onTwinUpdate`
 * subscription channel. Not an AppSync resolver itself; see appsyncClient.ts for why.
 */
export async function handler(rawEvent: EventBridgeLikeEvent): Promise<{ published: boolean }> {
  const { turbineId } = parseDetail(rawEvent);

  let latest;
  try {
    latest = await getLatestState(turbineId);
  } catch (err) {
    console.error("Failed to read latest twin state", { turbineId, err });
    throw new UpstreamError("Failed to read latest turbine state.", err);
  }

  if (!latest) {
    // Legitimate "no data yet" case (turbine has never reported telemetry) — not an
    // error, just nothing to publish this cycle.
    return { published: false };
  }

  const twinState: TwinState = {
    turbineId: latest.turbineId,
    timestamp: latest.updatedAt,
    pitchAngleDeg: latest.pitchAngleDeg,
    rotorSpeedRpm: latest.rotorSpeedRpm,
    componentHealth: latest.componentHealth,
  };

  try {
    await publishTwinUpdate(twinState);
  } catch (err) {
    console.error("Failed to publish twin update to AppSync", { turbineId, err });
    throw new UpstreamError("Failed to publish twin update.", err);
  }

  return { published: true };
}
