import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useFleet } from "../api/hooks";
import type { TurbineSummary } from "../api/types";
import { Card, Empty, HealthBadge, HealthBar, PageHead, QueryView, Segmented, SeverityBadge } from "../components/ui";
import { dataTime, pct, titleCase } from "../lib/format";

type SortKey = "health" | "id" | "alert";

const SEVERITY_RANK = { critical: 0, high: 1, medium: 2, low: 3 } as const;

function sortTurbines(list: TurbineSummary[], key: SortKey): TurbineSummary[] {
  const out = [...list];
  if (key === "id") out.sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }));
  if (key === "health") out.sort((a, b) => (a.health ?? 101) - (b.health ?? 101));
  if (key === "alert")
    out.sort(
      (a, b) =>
        (a.active_alert ? SEVERITY_RANK[a.active_alert.severity] : 9) -
        (b.active_alert ? SEVERITY_RANK[b.active_alert.severity] : 9),
    );
  return out;
}

export function TurbinesPage() {
  const [farm, setFarm] = useState("all");
  const [sort, setSort] = useState<SortKey>("health");
  const [q, setQ] = useState("");
  const fleet = useFleet(farm === "all" ? undefined : farm);

  const rows = useMemo(() => {
    const list = fleet.data?.turbines ?? [];
    const needle = q.trim().toLowerCase();
    return sortTurbines(
      needle ? list.filter((t) => `${t.id} ${t.name} ${t.worst_subcomponent ?? ""}`.toLowerCase().includes(needle)) : list,
      sort,
    );
  }, [fleet.data, q, sort]);

  return (
    <>
      <PageHead title="Turbines" lede="Every turbine with its current health, weakest sub-part, active alert and replay position." />
      <div className="filters">
        <Segmented
          label="Farm"
          value={farm}
          onChange={setFarm}
          options={[
            { value: "all", label: "All farms" },
            { value: "A", label: "A" },
            { value: "B", label: "B" },
            { value: "C", label: "C" },
          ]}
        />
        <Segmented
          label="Sort"
          value={sort}
          onChange={setSort}
          options={[
            { value: "health", label: "Lowest health" },
            { value: "alert", label: "Alert severity" },
            { value: "id", label: "Turbine" },
          ]}
        />
        <input
          className="input"
          placeholder="Search turbine or sub-part"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search turbines"
          style={{ width: 240 }}
        />
      </div>
      <Card flush>
        <QueryView query={fleet} height={400}>
          {() =>
            rows.length ? (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Turbine</th>
                      <th>Health</th>
                      <th>Status</th>
                      <th>Weakest sub-part</th>
                      <th>Active alert</th>
                      <th>Operating state</th>
                      <th>Data time (turbine clock)</th>
                      <th className="num">Replay</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((t) => (
                      <tr key={t.id}>
                        <td>
                          <Link to={`/turbines/${t.id}`} style={{ fontWeight: 600 }}>
                            {t.id}
                          </Link>
                          <div className="subtle">Farm {t.farm_id}</div>
                        </td>
                        <td style={{ width: 180 }}>
                          <HealthBar health={t.health} />
                        </td>
                        <td>
                          <HealthBadge health={t.health} showValue={false} />
                          {t.alarm && <span className="badge critical" style={{ marginLeft: 4 }}>detector alarm</span>}
                        </td>
                        <td>{t.worst_subcomponent ? titleCase(t.worst_subcomponent.split(".").pop() ?? "") : "—"}
                          {t.worst_subcomponent && <div className="subtle">{titleCase(t.worst_subcomponent.split(".")[0] ?? "")}</div>}
                        </td>
                        <td>
                          {t.active_alert ? (
                            <Link to={`/alerts?id=${t.active_alert.id}`}>
                              <SeverityBadge severity={t.active_alert.severity} />
                            </Link>
                          ) : (
                            <span className="subtle">none</span>
                          )}
                        </td>
                        <td>{t.replay?.operating_status_label ?? "—"}</td>
                        <td className="num" style={{ textAlign: "left" }}>{dataTime(t.replay?.cursor_ts)}</td>
                        <td className="num">
                          {pct(t.replay?.progress, 0)}
                          <div className="subtle">cycle {(t.replay?.cycle ?? 0) + 1}</div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty title="No turbine matches the filters" />
            )
          }
        </QueryView>
      </Card>
    </>
  );
}
