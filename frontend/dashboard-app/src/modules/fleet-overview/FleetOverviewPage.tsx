import { Link } from "react-router-dom";
import fleetSummaryRaw from "./data/fleetSummary.json";
import type { FleetSummary } from "./types";
import { StatTile } from "../../shared/StatTile";
import { ALL_TURBINES } from "../../shared/turbines";
import { FaultCategoryByFarmChart } from "./components/FaultCategoryByFarmChart";
import { AnomalyVsNormalChart } from "./components/AnomalyVsNormalChart";
import "./FleetOverviewPage.css";

const summary = fleetSummaryRaw as FleetSummary;

function topCategorySublabel(): string {
  const counts = summary.fleet_totals.anomaly_count_by_category;
  const top = summary.headline_kpis.most_common_named_fault_category;
  const tiedWith = Object.keys(counts).filter(
    (c) => c !== top && c !== "Other / unclassified" && counts[c] === counts[top],
  );
  const base = `${counts[top]} failures`;
  return tiedWith.length ? `${base} · tied with ${tiedWith.join(", ")}` : base;
}

export function FleetOverviewPage() {
  const kpis = summary.headline_kpis;
  const warning = kpis.fault_to_downtime_hours;

  return (
    <div className="fleet-overview">
      <header className="module-header">
        <h1>Fleet Overview</h1>
        <p className="module-subtitle">
          {summary.fleet_totals.total_turbines} turbines · {Object.keys(summary.farms).length} wind farms
        </p>
      </header>

      <section className="tile-row">
        <StatTile
          label="Turbines"
          value={String(summary.fleet_totals.total_turbines)}
          sublabel={`A: ${summary.farms.A.n_turbines} · B: ${summary.farms.B.n_turbines} · C: ${summary.farms.C.n_turbines}`}
        />
        <StatTile
          label="Failures"
          value={String(kpis.total_anomaly_events)}
          sublabel={`${summary.fleet_totals.total_normal_events} normal periods`}
        />
        <StatTile
          label="Top fault type"
          value={kpis.most_common_named_fault_category}
          sublabel={topCategorySublabel()}
        />
        <StatTile
          label="Warning before shutdown"
          value={warning.median_hours === null ? "n/a" : `~${Math.round(warning.median_hours)} h`}
          sublabel={`Typical range ${Math.round(warning.p25_hours ?? 0)}–${Math.round(warning.p75_hours ?? 0)} h`}
        />
      </section>

      <section className="chart-grid">
        <div className="chart-card">
          <h2>Anomaly vs. normal events by farm</h2>
          <AnomalyVsNormalChart summary={summary} />
        </div>
        <div className="chart-card">
          <h2>Fault category by farm</h2>
          <FaultCategoryByFarmChart summary={summary} />
        </div>
      </section>

      {/* <section className="data-note">
        <strong>Reading these numbers:</strong> Farm B's 6 anomaly events all fall under
        "Other / unclassified" - its real event text describes main/rotor bearing damage and
        generic high-temperature alarms, which sit outside this taxonomy's gearbox/hydraulics/
        pitch categories entirely (see EDA_REPORT.md §2). Farm C is dominated by Pitch / blade
        angle faults (8), consistent with its 3-axis independent pitch control design. Farm A has
        zero pitch-system anomaly events and matches its documented hydraulic/gearbox/generator/
        transformer fault list exactly.
      </section> */}

      <section className="turbine-picker">
        <h2>Turbines</h2>
        <div className="farm-columns">
          {Object.entries(summary.farms).map(([farmId, farm]) => (
            <div key={farmId} className="farm-column">
              <h3>{farm.label}</h3>
              <ul>
                {ALL_TURBINES.filter((t) => t.farmId === farmId).map((t) => (
                  <li key={t.id}>
                    <span className="turbine-id">{t.id}</span>
                    <Link to={`/assets/${t.id}`}>Detail</Link>
                    <Link to={`/twin/${t.id}`}>Twin</Link>
                    <Link to={`/forecasts/${t.id}`}>Forecast</Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
