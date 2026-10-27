import { Suspense, lazy, useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { FleetOverviewPage } from "./modules/fleet-overview/FleetOverviewPage";
import { AssetDetailPage } from "./modules/asset-detail/AssetDetailPage";
import { ForecastsRulPage } from "./modules/forecasts-rul/ForecastsRulPage";
import { AlertsPage } from "./modules/alerts/AlertsPage";
import { ChatAssistant } from "./shared/ChatAssistant";
import { AppearanceSettings } from "./shared/AppearanceSettings";
import { TurbineLoader } from "./shared/TurbineLoader";
import { APP_SUBTITLE, APP_TITLE } from "./config/appearance";
import { subscribeDemoData } from "./api/dataSource";
import { IconActivity, IconBell, IconClose, IconCube, IconGrid, IconMenu, IconTrend, IconTurbine } from "./shared/icons";
import "./App.css";

// three.js + fiber/drei are the single largest dependency in this app; code-split
// the digital twin route so the other four modules don't pay for it on load.
const DigitalTwinPage = lazy(() =>
  import("./modules/digital-twin/DigitalTwinPage").then((m) => ({ default: m.DigitalTwinPage })),
);

const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? "nav-link active" : "nav-link");

function useDemoAreas(): string[] {
  const [areas, setAreas] = useState<string[]>([]);
  useEffect(() => subscribeDemoData(setAreas), []);
  return areas;
}

export function App() {
  const { pathname } = useLocation();
  const turbineId = pathname.match(/^\/(?:assets|twin|forecasts)\/([^/]+)/)?.[1];
  const demoAreas = useDemoAreas();
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => setNavOpen(false), [pathname]);

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="app-shell">
        <aside className={`app-sidebar${navOpen ? " open" : ""}`}>
          <div className="brand">
            <span className="brand-logo">
              <IconTurbine width={22} height={22} />
            </span>
            <div className="brand-text">
              <strong>{APP_TITLE}</strong>
              <span>{APP_SUBTITLE}</span>
            </div>
            <button
              type="button"
              className="nav-toggle"
              aria-label={navOpen ? "Close menu" : "Open menu"}
              aria-expanded={navOpen}
              onClick={() => setNavOpen((o) => !o)}
            >
              {navOpen ? <IconClose /> : <IconMenu />}
            </button>
          </div>

          <div className="sidebar-body">
            <nav aria-label="Main">
              <div className="nav-section">Monitor</div>
              <NavLink to="/" end className={navClass}>
                <IconGrid /> Fleet Overview
              </NavLink>
              <NavLink to="/alerts" className={navClass}>
                <IconBell /> Alerts
              </NavLink>

              {turbineId && (
                <>
                  <div className="nav-section">Turbine {turbineId}</div>
                  <NavLink to={`/assets/${turbineId}`} className={navClass}>
                    <IconActivity /> Asset Detail
                  </NavLink>
                  <NavLink to={`/twin/${turbineId}`} className={navClass}>
                    <IconCube /> Digital Twin
                  </NavLink>
                  <NavLink to={`/forecasts/${turbineId}`} className={navClass}>
                    <IconTrend /> Forecasts &amp; RUL
                  </NavLink>
                </>
              )}
            </nav>

            {!turbineId && <p className="nav-hint">Select a turbine from Fleet Overview.</p>}

            <div className="sidebar-footer">
              <div className={`data-source ${demoAreas.length ? "demo" : "live"}`} role="status">
                <span className="dot" />
                {demoAreas.length ? "Demo data" : "Live data"}
              </div>
              <AppearanceSettings />
            </div>
          </div>
        </aside>

        <main id="main" className="app-main" tabIndex={-1}>
          <div className="app-content">
            <Routes>
              <Route path="/" element={<FleetOverviewPage />} />
              <Route path="/alerts" element={<AlertsPage />} />
              <Route path="/assets/:turbineId" element={<AssetDetailPage />} />
              <Route
                path="/twin/:turbineId"
                element={
                  <Suspense fallback={<TurbineLoader label="Loading digital twin…" />}>
                    <DigitalTwinPage />
                  </Suspense>
                }
              />
              <Route path="/forecasts/:turbineId" element={<ForecastsRulPage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </div>
        </main>
        <ChatAssistant />
      </div>
    </>
  );
}

function NotFound() {
  return (
    <div className="module-header">
      <h1>Page not found</h1>
      <p className="module-subtitle">
        No page matches this address. <NavLink to="/">Go to Fleet Overview</NavLink>
      </p>
    </div>
  );
}
