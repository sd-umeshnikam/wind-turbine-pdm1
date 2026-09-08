import fleetSummary from "../modules/fleet-overview/data/fleetSummary.json";
import type { FleetSummary } from "../modules/fleet-overview/types";

const summary = fleetSummary as FleetSummary;

export interface TurbineRef {
  id: string;
  farmId: string;
  farmLabel: string;
}

// The EDA fixture records per-farm turbine *counts* (distinct asset_id
// values), not the individual anonymized asset_id strings - those aren't
// published in fleet_summary.json. IDs below (e.g. "A-1") are synthesized
// only so the UI has something stable to route/link on; the counts driving
// them (5 / 9 / 22) are the real numbers from the fixture.
export const ALL_TURBINES: TurbineRef[] = Object.entries(summary.farms).flatMap(
  ([farmId, farm]) =>
    Array.from({ length: farm.n_turbines }, (_, i) => ({
      id: `${farmId}-${i + 1}`,
      farmId,
      farmLabel: farm.label,
    })),
);

export function turbineExists(turbineId: string): boolean {
  return ALL_TURBINES.some((t) => t.id === turbineId);
}
