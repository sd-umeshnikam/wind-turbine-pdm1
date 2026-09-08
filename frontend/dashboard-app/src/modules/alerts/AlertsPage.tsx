import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { acknowledgeAlert, getActiveAlerts } from "../../api/client";
import type { Alert } from "../../api/types";
import { SeverityBadge } from "../../shared/HealthPill";
import "./AlertsPage.css";

export function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());

  useEffect(() => {
    getActiveAlerts().then(setAlerts);
  }, []);

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
        <p className="module-subtitle">Fleet-wide active alerts, mock-backed until AppSync is live.</p>
      </header>

      {!alerts ? (
        <p>Loading alerts…</p>
      ) : (
        <table className="alerts-table">
          <thead>
            <tr>
              <th>Severity</th>
              <th>Turbine</th>
              <th>Component</th>
              <th>Message</th>
              <th>Created</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {alerts.map((a) => (
              <tr key={a.id} className={a.acknowledged ? "acknowledged" : ""}>
                <td>
                  <SeverityBadge severity={a.severity} />
                </td>
                <td>
                  <Link to={`/assets/${a.turbineId}`}>{a.turbineId}</Link>
                </td>
                <td>{a.component}</td>
                <td>{a.message}</td>
                <td>{new Date(a.createdAt).toLocaleString()}</td>
                <td>{a.acknowledged ? "Acknowledged" : "Active"}</td>
                <td>
                  {!a.acknowledged && (
                    <button
                      disabled={pending.has(a.id)}
                      onClick={() => handleAcknowledge(a.id)}
                    >
                      {pending.has(a.id) ? "…" : "Acknowledge"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
