/**
 * Local substitute for the two EventBridge triggers (see BLUEPRINT.md §5,
 * ADR-0004) - a plain `setInterval` loop, not a real scheduler, documented as a
 * deliberate simplification (not worth standing up an EventBridge-equivalent for
 * one box).
 *
 * Each tick: for every known turbine x component with a trained model, calls
 * prediction-api for a real prediction, then feeds it into alerting-service's
 * evaluate-and-alert write path - the same real handler code Query.activeAlerts
 * reads from (see Phase 0's fix to alerting-service/src/handler.ts).
 *
 * digital-twin-service is intentionally NOT wired here: both the cloud and local
 * architectures assume something populates a "latest twin state" table that,
 * looking at the actual code, nothing currently writes - a pre-existing gap
 * (see services/digital-twin-service/src/twinStateStore.ts's comment), not
 * something introduced by local hosting. The frontend's Digital Twin page keeps
 * using its own client-side mock ticker, which already works standalone.
 */
import { handler as predictionHandler } from "../../../services/prediction-api/src/handler.ts";
import { handler as alertingHandler } from "../../../services/alerting-service/src/handler.ts";
import { listDisplayTurbineIds } from "./turbineIds.ts";

const COMPONENTS = [
  "gearbox", "hydraulics", "pitch", "generator", "transformer", "rotor_brake", "vibration",
];

const TICK_INTERVAL_MS = Number(process.env.SCHEDULER_INTERVAL_MS ?? 60_000);

async function tick(): Promise<void> {
  const turbineIds = listDisplayTurbineIds();
  if (turbineIds.length === 0) {
    console.warn("[scheduler] no turbines found yet - run the pipeline (run_pipeline.sh) first");
    return;
  }

  for (const turbineId of turbineIds) {
    for (const component of COMPONENTS) {
      let predictions;
      try {
        predictions = await predictionHandler({ arguments: { turbineId, component } });
      } catch (err) {
        console.error("[scheduler] prediction-api call failed", { turbineId, component, err });
        continue;
      }
      if (!predictions.length) continue;

      const [prediction] = predictions;
      try {
        await alertingHandler({
          "detail-type": "prediction.updated",
          detail: {
            turbineId,
            component,
            faultProbability: prediction.faultProbability,
            rulHoursP50: prediction.rulHoursP50,
          },
        });
      } catch (err) {
        console.error("[scheduler] alerting-service call failed", { turbineId, component, err });
      }
    }
  }
}

export function startScheduler(): void {
  console.log(`[scheduler] starting, interval=${TICK_INTERVAL_MS}ms`);
  tick().catch((err) => console.error("[scheduler] initial tick failed", err));
  setInterval(() => {
    tick().catch((err) => console.error("[scheduler] tick failed", err));
  }, TICK_INTERVAL_MS);
}
