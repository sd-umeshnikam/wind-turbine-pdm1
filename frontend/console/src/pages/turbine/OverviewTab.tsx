import { useEffect, useRef } from "react";
import { useAlert, useSnapshot } from "../../api/hooks";
import { RecommendationView } from "../../assistant/RecommendationView";
import type { ComponentHealth, TurbineDetail } from "../../api/types";
import { Card, Empty, HealthBadge, HealthBar, QueryView } from "../../components/ui";
import { dataTime, num, titleCase, withUnit } from "../../lib/format";

function ComponentCard({
  component,
  focused,
  onSensor,
}: {
  component: ComponentHealth;
  focused: boolean;
  onSensor: (code: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focused]);
  return (
    <div ref={ref} style={focused ? { outline: "2px solid var(--focus)", borderRadius: 8 } : undefined}>
      <Card
        title={component.name}
        hint={`${component.subparts.length} sub-part${component.subparts.length === 1 ? "" : "s"}`}
        tools={<HealthBadge health={component.health} />}
        flush
      >
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Sub-part</th>
                <th style={{ width: 200 }}>Health</th>
                <th className="num" title="Standardised deviation of the monitored sensors from the normal-behaviour model">
                  Residual z
                </th>
                <th>Monitored signals</th>
              </tr>
            </thead>
            <tbody>
              {component.subparts.map((sp) => (
                <tr key={sp.code}>
                  <td>
                    <div style={{ fontWeight: 500 }}>{sp.name}</div>
                    <div className="subtle">{sp.ts ? `scored ${dataTime(sp.ts)}` : "no recent score"}</div>
                  </td>
                  <td>
                    <HealthBar health={sp.health} />
                  </td>
                  <td className="num">{num(sp.residual_z, 2)}</td>
                  <td>
                    {sp.sensors.length ? (
                      <ul style={{ margin: 0, paddingLeft: 16 }}>
                        {sp.sensors.map((s) => (
                          <li key={s.code}>
                            <button
                              className="btn ghost sm"
                              style={{ height: "auto", padding: "1px 4px", textAlign: "left", whiteSpace: "normal" }}
                              onClick={() => onSensor(s.code)}
                              title="Show expected vs actual"
                            >
                              {s.description}
                              {s.unit && <span className="subtle"> ({s.unit})</span>}
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="subtle">no sensor on this farm</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function Conditions({ turbineId }: { turbineId: string }) {
  const snap = useSnapshot(turbineId);
  return (
    <Card title="Operating conditions" hint="at the replay cursor">
      <QueryView query={snap} height={160}>
        {(s) =>
          s.readings.length ? (
            <dl className="kv">
              {s.readings.map((r) => (
                <div key={r.code} style={{ display: "contents" }}>
                  <dt title={`${r.code} · ${titleCase(r.kind)}`}>{r.description}</dt>
                  <dd className="num">{r.value === null ? <span className="subtle">no reading</span> : withUnit(r.value, r.unit)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <Empty title="No condition sensors" />
          )
        }
      </QueryView>
    </Card>
  );
}

function Drivers({ alertId }: { alertId: string }) {
  const alert = useAlert(alertId);
  return (
    <Card title="Alert drivers" hint="largest deviations from expected behaviour">
      <QueryView query={alert} height={120}>
        {(a) =>
          a.drivers?.length ? (
            <table className="data">
              <tbody>
                {a.drivers.map((d) => (
                  <tr key={d.sensor}>
                    <td>{d.description}</td>
                    <td className="num" style={{ color: Math.abs(d.z) >= 3 ? "var(--danger-ink)" : undefined }}>
                      z {d.z > 0 ? "+" : ""}
                      {num(d.z, 1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty title="No drivers recorded" />
          )
        }
      </QueryView>
      <p className="subtle" style={{ marginBottom: 0 }}>
        Sub-part attribution is a contributing signal, not a confirmed diagnosis.
      </p>
    </Card>
  );
}

export function OverviewTab({
  turbine,
  focus,
  onSensor,
}: {
  turbine: TurbineDetail;
  focus: string | null;
  onSensor: (sensor: string) => void;
}) {
  return (
    <div className="grid cols-main-side">
      <div className="stack">
        {turbine.components_tree.length ? (
          turbine.components_tree.map((c) => (
            <ComponentCard key={c.code} component={c} focused={focus === c.code} onSensor={onSensor} />
          ))
        ) : (
          <Card>
            <Empty title="No monitored components">This farm's taxonomy maps no sensors to sub-parts.</Empty>
          </Card>
        )}
      </div>
      <div className="stack">
        <Conditions turbineId={turbine.id} />
        {turbine.active_alert && <Drivers alertId={turbine.active_alert.id} />}
        <Card title="Maintenance outlook" hint="advisory, from the playbook">
          <RecommendationView turbineId={turbine.id} />
        </Card>
      </div>
    </div>
  );
}
