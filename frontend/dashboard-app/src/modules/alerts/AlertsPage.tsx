import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { acknowledgeAlert, getActiveAlerts } from "../../api/client";
import type { Alert } from "../../api/types";
import { SeverityBadge } from "../../shared/HealthPill";
import { TurbineLoader } from "../../shared/TurbineLoader";
import "./AlertsPage.css";

const SEVERITY_ORDER = ["critical", "high", "medium", "low"];
const rank = (s: string) => {
  const i = SEVERITY_ORDER.indexOf(s.toLowerCase());
  return i === -1 ? SEVERITY_ORDER.length : i;
};

export function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<string>("all");

  useEffect(() => {
    getActiveAlerts().then(setAlerts);
  }, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const a of alerts ?? []) c[a.severity.toLowerCase()] = (c[a.severity.toLowerCase()] ?? 0) + 1;
    return c;
  }, [alerts]);

  const visible = useMemo(
    () =>
      [...(alerts ?? [])]
        .filter((a) => filter === "all" || a.severity.toLowerCase() === filter)
        .sort((a, b) => rank(a.severity) - rank(b.severity) || b.createdAt.localeCompare(a.createdAt)),
    [alerts, filter],
  );

  async function handleAcknowledge(id: string) {
    setPending((prev) => new Set(prev).add(id));
    // Optimistic update: acknowledgeAlert is a stub with no real backend yet.
    await acknowledgeAlert(id);
    setAlerts((prev) => prev?.map((a) => (a.id === id ? { ...a, acknowledged: true } : a)) ?? null);
    setPending((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }

  return (
    <div className="alerts-page">
      <header className="module-header">
        <h1>Active Alerts</h1>
        <p className="module-subtitle">Most urgent first.</p>
      </header>

      {!alerts ? (
        <TurbineLoader label="Loading alerts…" />
      ) : alerts.length === 0 ? (
        <div className="card empty-state">No active alerts.</div>
      ) : (
        <>
          <div className="tabs" role="tablist" aria-label="Filter by severity">
            {["all", ...SEVERITY_ORDER.filter((s) => counts[s])].map((s) => (
              <button
                key={s}
                type="button"
                role="tab"
                aria-selected={filter === s}
                className={filter === s ? "tab active" : "tab"}
                onClick={() => setFilter(s)}
              >
                {s === "all" ? "All" : s[0].toUpperCase() + s.slice(1)} ({s === "all" ? alerts.length : counts[s]})
              </button>
            ))}
          </div>

          <div className="table-wrap">
            <table className="data-table alerts-table">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Turbine</th>
                  <th>Component</th>
                  <th>Details</th>
                  <th>Raised</th>
                  <th>
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((a) => (
                  <tr key={a.id} className={a.acknowledged ? "acknowledged" : ""}>
                    <td>
                      <SeverityBadge severity={a.severity} />
                    </td>
                    <td>
                      <Link to={`/assets/${a.turbineId}`}>{a.turbineId}</Link>
                    </td>
                    <td className="capitalize">{a.component.replace(/_/g, " ")}</td>
                    <td className="alert-message">{a.message}</td>
                    <td className="nowrap">{new Date(a.createdAt).toLocaleString()}</td>
                    <td>
                      {a.acknowledged ? (
                        <span className="muted">Acknowledged</span>
                      ) : (
                        <button
                          type="button"
                          className="btn"
                          disabled={pending.has(a.id)}
                          onClick={() => handleAcknowledge(a.id)}
                        >
                          {pending.has(a.id) ? "Saving…" : "Acknowledge"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
