// Advisory maintenance recommendation from the playbook for an alert or a turbine: response
// window from the severity, implicated sub-parts with the live evidence, likely failure
// modes with checks and actions.

import { ShieldAlert, Sparkles } from "lucide-react";
import { useRecommendation } from "../api/hooks";
import { Badge, Empty, ErrorState, Loading } from "../components/ui";
import { num } from "../lib/format";
import { useAssistant } from "./Assistant";

export function RecommendationView({ alertId, turbineId }: { alertId?: string; turbineId?: string }) {
  const q = useRecommendation(alertId ? { alert_id: alertId } : { turbine_id: turbineId });
  const { ask } = useAssistant();
  if (q.isLoading) return <Loading height={140} />;
  if (q.error && !q.data) return <ErrorState error={q.error} retry={() => void q.refetch()} />;
  const r = q.data!;
  return (
    <div className="stack" style={{ gap: 10 }}>
      {r.response && (
        <div className="row" style={{ gap: 8 }}>
          <Badge tone={r.severity === "critical" ? "critical" : r.severity === "high" ? "serious" : "warning"}>
            Respond {r.response.window}
          </Badge>
          <span className="subtle">{r.response.posture}</span>
        </div>
      )}
      {r.items.length === 0 && <Empty title="No maintenance action needed">{r.notes[0]}</Empty>}
      {r.items.map((item) => (
        <div key={item.subcomponent} className="card" style={{ padding: 12, boxShadow: "none" }}>
          <div className="row" style={{ gap: 8 }}>
            <strong style={{ flex: 1 }}>{item.name}</strong>
            {item.safety_relevant && (
              <Badge tone="critical">
                <ShieldAlert size={12} /> safety-relevant
              </Badge>
            )}
          </div>
          {item.evidence.length > 0 && (
            <div className="subtle" style={{ marginTop: 4 }}>
              Evidence:{" "}
              {item.evidence
                .map((e) =>
                  e.description
                    ? `${e.description} (z ${e.z !== undefined && e.z > 0 ? "+" : ""}${num(e.z, 1)})`
                    : `health ${num(e.health, 0)}${e.residual_z !== null && e.residual_z !== undefined ? `, residual z ${num(e.residual_z, 1)}` : ""}`,
                )
                .join("; ")}
            </div>
          )}
          {item.failure_modes.map((fm) => (
            <div key={fm.id} style={{ marginTop: 8 }}>
              <div>
                <span className="badge outline mono">{fm.id}</span> {fm.mode}
              </div>
              <div className="grid cols-2" style={{ gap: 8, marginTop: 6 }}>
                <div>
                  <div className="subtle" style={{ fontWeight: 600 }}>Checks</div>
                  <ul style={{ margin: "2px 0 0", paddingLeft: 18 }}>
                    {fm.checks.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="subtle" style={{ fontWeight: 600 }}>Actions</div>
                  <ul style={{ margin: "2px 0 0", paddingLeft: 18 }}>
                    {fm.actions.map((a) => (
                      <li key={a}>{a}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          ))}
        </div>
      ))}
      {r.items.length > 0 && r.notes.map((n) => <div key={n} className="subtle">{n}</div>)}
      <div className="row" style={{ gap: 8 }}>
        <span className="subtle" style={{ flex: 1 }}>
          {r.disclaimer}
        </span>
        <button
          className="btn sm"
          onClick={() =>
            ask(
              alertId
                ? `What maintenance do you recommend for the alert on ${r.turbine_id}, and why?`
                : `What maintenance does ${r.turbine_id} need right now?`,
            )
          }
        >
          <Sparkles size={13} /> Discuss with assistant
        </button>
      </div>
    </div>
  );
}
