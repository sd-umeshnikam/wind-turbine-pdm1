import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../api/client";
import { useAlert, useAlertAction, useDirectory, type AlertAction } from "../../api/hooks";
import type { AlertDetail, AuditEntry, Note } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { useToast } from "../../components/Toasts";
import { Drawer, ErrorState, Loading, SeverityBadge, StatusBadge } from "../../components/ui";
import { dataTime, num, titleCase, wallTime } from "../../lib/format";

type Entry = { ts: string; kind: "note"; note: Note } | { ts: string; kind: "audit"; audit: AuditEntry };

const ACTION_TEXT: Record<string, string> = {
  "alert.raise": "Alert raised",
  "alert.escalate": "Severity escalated",
  "alert.clear": "Condition cleared",
  "alert.reoccur": "Condition re-occurred",
  "alert.acknowledge": "Acknowledged",
  "alert.assign": "Assignment changed",
  "alert.resolve": "Resolved",
  "alert.note": "Note added",
};

function auditText(a: AuditEntry): string {
  const base = ACTION_TEXT[a.action] ?? titleCase(a.action.replace("alert.", ""));
  const d = a.details ?? {};
  if (a.action === "alert.assign") return `${base}: ${d.previous ?? "unassigned"} → ${d.assignee ?? "unassigned"}`;
  if (a.action === "alert.escalate" && d.to) return `${base}: ${d.from} → ${d.to}`;
  if (a.action === "alert.raise" && d.severity) return `${base} (${d.severity}, health ${d.health})`;
  return base;
}

function Timeline({ alert }: { alert: AlertDetail }) {
  const entries: Entry[] = [
    ...alert.notes.map((n): Entry => ({ ts: n.created_at, kind: "note", note: n })),
    ...alert.audit.filter((a) => a.action !== "alert.note").map((a): Entry => ({ ts: a.ts, kind: "audit", audit: a })),
  ].sort((a, b) => a.ts.localeCompare(b.ts));
  if (!entries.length) return <p className="subtle">No activity yet.</p>;
  return (
    <ol className="timeline">
      {entries.map((e) => (
        <li key={`${e.kind}-${e.kind === "note" ? e.note.id : e.audit.id}`}>
          <span className="tl-dot" style={e.kind === "note" ? { background: "var(--series-3)" } : undefined} />
          <div>
            {e.kind === "note" ? (
              <>
                <div style={{ whiteSpace: "pre-wrap" }}>{e.note.body}</div>
                <div className="subtle">
                  {e.note.author} · {wallTime(e.ts)}
                </div>
              </>
            ) : (
              <>
                <div style={{ fontWeight: 500 }}>{auditText(e.audit)}</div>
                <div className="subtle">
                  {e.audit.actor} · {wallTime(e.ts)}
                </div>
              </>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

function Actions({ alert }: { alert: AlertDetail }) {
  const { can, user } = useAuth();
  const toast = useToast();
  const action = useAlertAction(alert.id);
  const directory = useDirectory(can("engineer"));
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"note" | "resolve">("note");

  if (!can("engineer")) return <p className="subtle">Viewers can follow alerts; acknowledging and resolving needs the engineer role.</p>;

  const run = (a: AlertAction, done: string) =>
    action.mutate(a, {
      onSuccess: () => {
        toast(done);
        setText("");
      },
      onError: (err) =>
        toast(err instanceof ApiError && err.status === 409 ? `${err.message} (refreshed)` : `Failed: ${err.message}`, "error"),
    });

  const active = alert.status !== "resolved";
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row">
        {alert.status === "open" && (
          <button className="btn primary" disabled={action.isPending} onClick={() => run({ kind: "acknowledge", note: text.trim() || undefined }, "Alert acknowledged")}>
            Acknowledge{text.trim() ? " with note" : ""}
          </button>
        )}
        {active && (
          <select
            className="select"
            aria-label="Assignee"
            value={alert.assignee ?? ""}
            disabled={action.isPending}
            onChange={(e) => run({ kind: "assign", assignee: e.target.value || null }, "Assignment updated")}
          >
            <option value="">Unassigned</option>
            {(directory.data ?? []).map((u) => (
              <option key={u.username} value={u.username}>
                {u.display_name} ({u.username})
              </option>
            ))}
          </select>
        )}
        {active && alert.assignee !== user?.username && (
          <button className="btn" disabled={action.isPending} onClick={() => run({ kind: "assign", assignee: user!.username }, "Assigned to you")}>
            Take ownership
          </button>
        )}
      </div>
      <div className="field">
        <div className="row">
          <span className="label" style={{ flex: 1 }}>
            {mode === "resolve" ? "Resolution: what was found and done" : "Note"}
          </span>
          {active && (
            <div className="segmented" role="group" aria-label="Entry type">
              <button aria-pressed={mode === "note"} onClick={() => setMode("note")}>
                Note
              </button>
              <button aria-pressed={mode === "resolve"} onClick={() => setMode("resolve")}>
                Resolve
              </button>
            </div>
          )}
        </div>
        <textarea className="textarea" rows={3} value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} />
      </div>
      <div className="row">
        {mode === "resolve" && active ? (
          <button
            className="btn primary"
            disabled={action.isPending || text.trim().length < 3}
            onClick={() => run({ kind: "resolve", resolution: text.trim() }, "Alert resolved")}
          >
            Resolve alert
          </button>
        ) : (
          <button className="btn" disabled={action.isPending || !text.trim()} onClick={() => run({ kind: "note", body: text.trim() }, "Note added")}>
            Add note
          </button>
        )}
        {mode === "resolve" && alert.condition_active && (
          <span className="subtle">The condition is still present; it will re-open as a new alert if it persists.</span>
        )}
      </div>
    </div>
  );
}

export function AlertDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useAlert(id);
  const a = q.data;
  return (
    <Drawer
      title={a?.title ?? "Alert"}
      onClose={onClose}
      head={
        a && (
          <div className="row" style={{ marginTop: 6 }}>
            <SeverityBadge severity={a.severity} />
            <StatusBadge status={a.status} />
            {a.condition_active ? <span className="badge critical">condition present</span> : <span className="badge good">condition cleared</span>}
          </div>
        )
      }
    >
      {q.isLoading ? (
        <Loading height={300} />
      ) : q.error || !a ? (
        <ErrorState error={q.error} retry={() => void q.refetch()} />
      ) : (
        <div className="stack">
          <p style={{ margin: 0 }}>{a.message}</p>
          <dl className="kv">
            <dt>Turbine</dt>
            <dd>
              <Link to={`/turbines/${a.turbine_id}`}>{a.turbine_id}</Link> · Farm {a.farm_id}
            </dd>
            <dt>Component</dt>
            <dd>
              {titleCase(a.component_code)}
              {a.subcomponent_code && ` · ${a.subcomponent_code}`}
            </dd>
            <dt>Model</dt>
            <dd>{a.model_version ?? "—"}</dd>
            <dt>Data time</dt>
            <dd>
              {dataTime(a.data_ts)} → {dataTime(a.last_data_ts)}
            </dd>
            <dt>Opened</dt>
            <dd>{wallTime(a.opened_at)}</dd>
            <dt>Owner</dt>
            <dd>{a.assignee ?? "unassigned"}</dd>
            {a.resolved_at && (
              <>
                <dt>Resolved</dt>
                <dd>
                  {wallTime(a.resolved_at)} by {a.resolved_by}
                </dd>
              </>
            )}
          </dl>
          {a.drivers && a.drivers.length > 0 && (
            <div>
              <h3 style={{ marginBottom: 6 }}>Drivers</h3>
              <table className="data">
                <thead>
                  <tr>
                    <th>Signal</th>
                    <th className="num">Deviation (z)</th>
                  </tr>
                </thead>
                <tbody>
                  {a.drivers.map((d) => (
                    <tr key={d.sensor}>
                      <td>
                        <Link to={`/turbines/${a.turbine_id}?tab=expected&sensor=${d.sensor.replace(/_avg$/, "")}`}>{d.description}</Link>
                        <div className="subtle">{d.sensor}</div>
                      </td>
                      <td className="num">
                        {d.z > 0 ? "+" : ""}
                        {num(d.z, 1)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="subtle">Sub-part attribution is a contributing signal, not a confirmed diagnosis.</p>
            </div>
          )}
          <div>
            <h3 style={{ marginBottom: 8 }}>Actions</h3>
            <Actions alert={a} />
          </div>
          <div>
            <h3 style={{ marginBottom: 8 }}>Activity</h3>
            <Timeline alert={a} />
          </div>
        </div>
      )}
    </Drawer>
  );
}
