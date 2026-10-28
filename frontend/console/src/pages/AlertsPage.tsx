import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAlertSummary, useAlerts } from "../api/hooks";
import type { Query } from "../api/client";
import type { Severity } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Card, Empty, PageHead, QueryView, Segmented, SeverityBadge, StatusBadge } from "../components/ui";
import { ago, dataTime, titleCase } from "../lib/format";
import { SEVERITY_LABEL, SEVERITY_ORDER } from "../lib/health";
import { AlertDrawer } from "./alerts/AlertDrawer";

const PAGE = 25;
type StatusFilter = "active" | "open" | "acknowledged" | "resolved" | "all";
type Owner = "any" | "me" | "none";

export function AlertsPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const selected = params.get("id");
  const [status, setStatus] = useState<StatusFilter>("active");
  const [severity, setSeverity] = useState<Severity[]>([]);
  const [farm, setFarm] = useState("");
  const [owner, setOwner] = useState<Owner>("any");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("-opened_at");
  const [page, setPage] = useState(0);

  const filters = useMemo<Query>(
    () => ({
      active: status === "active" ? true : undefined,
      status: status === "open" || status === "acknowledged" || status === "resolved" ? status : undefined,
      severity,
      farm: farm || undefined,
      assignee: owner === "me" ? user?.username : owner === "none" ? "none" : undefined,
      q: q.trim() || undefined,
      sort,
      limit: PAGE,
      offset: page * PAGE,
    }),
    [status, severity, farm, owner, q, sort, page, user],
  );
  const alerts = useAlerts(filters);
  const summary = useAlertSummary();

  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setPage(0);
  };
  const open = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("id", id);
    else next.delete("id");
    setParams(next, { replace: true });
  };

  const s = summary.data;
  return (
    <>
      <PageHead
        title="Alerts"
        lede="Work queue for condition alerts raised by the health models. Engineers acknowledge, assign and resolve; every action is audited."
      />
      {s && (
        <div className="kpis">
          <div className="card kpi">
            <div className="kpi-label">Open</div>
            <div className="kpi-value">{s.by_status.open}</div>
            <div className="kpi-foot">awaiting acknowledgement</div>
          </div>
          <div className="card kpi">
            <div className="kpi-label">Acknowledged</div>
            <div className="kpi-value">{s.by_status.acknowledged}</div>
            <div className="kpi-foot">being worked</div>
          </div>
          <div className="card kpi">
            <div className="kpi-label">Unassigned (active)</div>
            <div className="kpi-value">{s.unassigned}</div>
            <div className="kpi-foot">no owner yet</div>
          </div>
          <div className="card kpi">
            <div className="kpi-label">Active by severity</div>
            <div className="row" style={{ marginTop: 8, gap: 6 }}>
              {SEVERITY_ORDER.map((sv) => (
                <span key={sv} className="row" style={{ gap: 4 }}>
                  <SeverityBadge severity={sv} />
                  <strong className="num">{s.by_severity[sv]}</strong>
                </span>
              ))}
            </div>
          </div>
          <div className="card kpi">
            <div className="kpi-label">Resolved</div>
            <div className="kpi-value">{s.by_status.resolved}</div>
            <div className="kpi-foot">all time</div>
          </div>
        </div>
      )}
      <div className="filters">
        <Segmented
          label="Status"
          value={status}
          onChange={reset(setStatus)}
          options={[
            { value: "active", label: "Active" },
            { value: "open", label: "Open" },
            { value: "acknowledged", label: "Acknowledged" },
            { value: "resolved", label: "Resolved" },
            { value: "all", label: "All" },
          ]}
        />
        <Segmented
          label="Owner"
          value={owner}
          onChange={reset(setOwner)}
          options={[
            { value: "any", label: "Anyone" },
            { value: "me", label: "Mine" },
            { value: "none", label: "Unassigned" },
          ]}
        />
        <select className="select" value={farm} onChange={(e) => reset(setFarm)(e.target.value)} aria-label="Farm">
          <option value="">All farms</option>
          <option value="A">Farm A</option>
          <option value="B">Farm B</option>
          <option value="C">Farm C</option>
        </select>
        <div className="segmented" role="group" aria-label="Severity">
          {SEVERITY_ORDER.map((sv) => (
            <button
              key={sv}
              aria-pressed={severity.includes(sv)}
              onClick={() => reset(setSeverity)(severity.includes(sv) ? severity.filter((x) => x !== sv) : [...severity, sv])}
            >
              {SEVERITY_LABEL[sv]}
            </button>
          ))}
        </div>
        <input
          className="input"
          placeholder="Search title or message"
          value={q}
          onChange={(e) => reset(setQ)(e.target.value)}
          aria-label="Search alerts"
          style={{ width: 220 }}
        />
        <select className="select" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
          <option value="-opened_at">Newest first</option>
          <option value="opened_at">Oldest first</option>
          <option value="-updated_at">Recently updated</option>
          <option value="-severity">Most severe</option>
        </select>
      </div>
      <Card flush>
        <QueryView query={alerts} height={400}>
          {(p) =>
            p.items.length ? (
              <>
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Severity</th>
                        <th>Alert</th>
                        <th>Turbine</th>
                        <th>Status</th>
                        <th>Condition</th>
                        <th>Owner</th>
                        <th>Opened</th>
                      </tr>
                    </thead>
                    <tbody>
                      {p.items.map((a) => (
                        <tr
                          key={a.id}
                          className={`clickable ${a.id === selected ? "selected" : ""}`}
                          onClick={() => open(a.id)}
                        >
                          <td>
                            <SeverityBadge severity={a.severity} />
                          </td>
                          <td style={{ maxWidth: 420 }}>
                            <button
                              className="btn ghost sm"
                              style={{ padding: 0, height: "auto", fontWeight: 600, whiteSpace: "normal", textAlign: "left" }}
                              onClick={(e) => {
                                e.stopPropagation();
                                open(a.id);
                              }}
                            >
                              {a.title}
                            </button>
                            <div className="subtle">
                              {titleCase(a.component_code)}
                              {a.subcomponent_code && ` · ${a.subcomponent_code.split(".").pop()}`} · data {dataTime(a.data_ts)}
                            </div>
                          </td>
                          <td>
                            <Link to={`/turbines/${a.turbine_id}`} onClick={(e) => e.stopPropagation()}>
                              {a.turbine_id}
                            </Link>
                          </td>
                          <td>
                            <StatusBadge status={a.status} />
                          </td>
                          <td>{a.condition_active ? <span className="badge critical">present</span> : <span className="badge good">cleared</span>}</td>
                          <td>{a.assignee ?? <span className="subtle">unassigned</span>}</td>
                          <td title={new Date(a.opened_at).toLocaleString()}>{ago(a.opened_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="pager">
                  <span>
                    {page * PAGE + 1}–{Math.min((page + 1) * PAGE, p.total)} of {p.total}
                  </span>
                  <button className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
                    Previous
                  </button>
                  <button className="btn sm" disabled={(page + 1) * PAGE >= p.total} onClick={() => setPage(page + 1)}>
                    Next
                  </button>
                </div>
              </>
            ) : (
              <Empty title="No alerts match these filters" />
            )
          }
        </QueryView>
      </Card>
      {selected && <AlertDrawer id={selected} onClose={() => open(null)} />}
    </>
  );
}
