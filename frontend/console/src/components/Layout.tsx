import {
  Activity,
  BellRing,
  BrainCircuit,
  Database,
  Gauge,
  LogOut,
  Monitor,
  Moon,
  ShieldCheck,
  Sun,
  TrendingUp,
  Wind,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useAlertSummary, useReplay } from "../api/hooks";
import { useStreamState } from "../api/stream";
import { useAuth } from "../auth/AuthContext";
import { ago } from "../lib/format";
import { useThemeChoice, type ThemeChoice } from "../lib/theme";
import { AssistantLauncher, AssistantProvider } from "../assistant/Assistant";

function Nav() {
  const { can } = useAuth();
  const summary = useAlertSummary();
  const open = summary.data?.by_status.open ?? 0;
  const link = ({ isActive }: { isActive: boolean }) => (isActive ? "nav-link active" : "nav-link");
  return (
    <nav className="sidebar" aria-label="Main">
      <div className="brand">
        <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden>
          <rect width="32" height="32" rx="7" fill="#256abf" />
          <g fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round">
            <path d="M16 15V28M16 15L16 4M16 15L6.5 20.5M16 15L25.5 20.5" />
          </g>
          <circle cx="16" cy="15" r="2.4" fill="#fff" />
        </svg>
        <div>
          <div className="brand-name">Wind PdM</div>
          <div className="brand-sub">Predictive maintenance</div>
        </div>
      </div>
      <div className="nav-section">Operations</div>
      <NavLink to="/" end className={link}>
        <Gauge size={17} /> Fleet overview
      </NavLink>
      <NavLink to="/turbines" className={link}>
        <Wind size={17} /> Turbines
      </NavLink>
      <NavLink to="/alerts" className={link}>
        <BellRing size={17} /> Alerts
        {open > 0 && <span className="nav-badge" aria-label={`${open} open alerts`}>{open}</span>}
      </NavLink>
      <div className="nav-section">Machine learning</div>
      <NavLink to="/models" className={link}>
        <BrainCircuit size={17} /> Models
      </NavLink>
      <NavLink to="/drift" className={link}>
        <TrendingUp size={17} /> Drift &amp; retraining
      </NavLink>
      <div className="nav-section">Data</div>
      <NavLink to="/data" className={link}>
        <Database size={17} /> Data &amp; replay
      </NavLink>
      {can("engineer") && (
        <>
          <div className="nav-section">Governance</div>
          <NavLink to="/admin" className={link}>
            <ShieldCheck size={17} /> {can("admin") ? "Users & audit" : "Audit log"}
          </NavLink>
        </>
      )}
      <div className="sidebar-foot">CARE wind-farm dataset · live replay of recorded SCADA history</div>
    </nav>
  );
}

function ReplayClock() {
  const replay = useReplay();
  const stream = useStreamState();
  const label = { live: "Live", connecting: "Connecting", offline: "Offline" }[stream];
  return (
    <div className="row" style={{ gap: 14, fontSize: 12 }}>
      <span className="row" style={{ gap: 6 }} title="Live update stream">
        <span className={`live-dot ${stream}`} aria-hidden />
        <span>{label}</span>
      </span>
      {replay.data && (
        <span className="row muted" style={{ gap: 6 }} title="Every turbine replays its own recorded SCADA history">
          <Activity size={14} aria-hidden />
          SCADA replay at {replay.data.speed.toLocaleString()}× · {replay.data.turbines.length} turbines · updated{" "}
          {ago(replay.data.last_update)}
        </span>
      )}
    </div>
  );
}

function ThemeToggle() {
  const [choice, setChoice] = useThemeChoice();
  const next: Record<ThemeChoice, ThemeChoice> = { system: "light", light: "dark", dark: "system" };
  const icon = { system: <Monitor size={16} />, light: <Sun size={16} />, dark: <Moon size={16} /> }[choice];
  return (
    <button
      className="btn ghost icon"
      onClick={() => setChoice(next[choice])}
      title={`Theme: ${choice} (click to change)`}
      aria-label={`Theme: ${choice}`}
    >
      {icon}
    </button>
  );
}

export function Layout() {
  const { user, logout } = useAuth();
  return (
    <AssistantProvider>
    <div className="shell">
      <Nav />
      <header className="topbar">
        <ReplayClock />
        <div className="spacer" />
        <AssistantLauncher />
        <ThemeToggle />
        {user && (
          <div className="row" style={{ gap: 10 }}>
            <div style={{ textAlign: "right", lineHeight: 1.2 }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{user.display_name}</div>
              <div className="subtle">{user.role}</div>
            </div>
            <button className="btn ghost icon" onClick={logout} title="Sign out" aria-label="Sign out">
              <LogOut size={16} />
            </button>
          </div>
        )}
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
    </AssistantProvider>
  );
}
