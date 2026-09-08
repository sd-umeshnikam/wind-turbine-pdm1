import { Suspense, lazy } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { FleetOverviewPage } from "./modules/fleet-overview/FleetOverviewPage";
import { AssetDetailPage } from "./modules/asset-detail/AssetDetailPage";
import { ForecastsRulPage } from "./modules/forecasts-rul/ForecastsRulPage";
import { AlertsPage } from "./modules/alerts/AlertsPage";
import "./App.css";

// three.js + fiber/drei are the single largest dependency in this app; code-split
// the digital twin route so the other four modules don't pay for it on load.
const DigitalTwinPage = lazy(() =>
  import("./modules/digital-twin/DigitalTwinPage").then((m) => ({ default: m.DigitalTwinPage })),
);

export function App() {
  return (
    <div className="app-shell">
      <nav className="app-nav">
        <div className="app-nav-title">Wind Turbine PdM</div>
        <NavLink to="/" end className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
          Fleet Overview
        </NavLink>
        <NavLink to="/alerts" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
          Alerts
        </NavLink>
        <div className="nav-hint">
          Per-turbine views (Asset Detail, Digital Twin, Forecasts) open from a turbine picked in
          Fleet Overview or Alerts.
        </div>
      </nav>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<FleetOverviewPage />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/assets/:turbineId" element={<AssetDetailPage />} />
          <Route
            path="/twin/:turbineId"
            element={
              <Suspense fallback={<p>Loading digital twin…</p>}>
                <DigitalTwinPage />
              </Suspense>
            }
          />
          <Route path="/forecasts/:turbineId" element={<ForecastsRulPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </div>
  );
}

function NotFound() {
  return (
    <div className="module-header">
      <h1>Not found</h1>
      <p className="module-subtitle">No route matches this URL.</p>
    </div>
  );
}
