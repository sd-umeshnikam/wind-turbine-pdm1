import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Written by local-stack/pipeline/02_silver_clean.py (see common.py's
// save_turbine_id_map_for_farm) - real (farm, asset_id) -> display id ("A-1", ...)
// mapping, so the gateway/scheduler and the frontend (which independently
// synthesizes the same "${farmId}-${i+1}" scheme - see
// frontend/dashboard-app/src/shared/turbines.ts) agree on turbine identifiers.

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_LAKE_ROOT = process.env.DATA_LAKE_ROOT
  ?? path.resolve(__dirname, "..", "..", "data-lake");
const MAP_PATH = path.join(DATA_LAKE_ROOT, "turbine_id_map.json");

type TurbineIdMap = Record<string, Record<string, number>>;

export function listDisplayTurbineIds(): string[] {
  if (!existsSync(MAP_PATH)) return [];
  const map = JSON.parse(readFileSync(MAP_PATH, "utf-8")) as TurbineIdMap;
  const ids: string[] = [];
  for (const [farm, assetRanks] of Object.entries(map)) {
    for (const rank of Object.values(assetRanks)) {
      ids.push(`${farm}-${rank}`);
    }
  }
  return ids;
}
