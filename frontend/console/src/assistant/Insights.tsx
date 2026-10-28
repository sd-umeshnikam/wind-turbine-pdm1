// Proactive insights: what changed since the user's previous visit (alerts raised or
// escalated, resolutions, the user's queue, model and retraining changes, drift, turbines
// below the watch level). Computed by the API from the audit log and live state.

import { CheckCircle2, Info, TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { useInsights } from "../api/hooks";
import type { Insight } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Empty, ErrorState, Loading } from "../components/ui";
import { ago } from "../lib/format";

const ICON: Record<Insight["tone"], JSX.Element> = {
  critical: <TriangleAlert size={15} style={{ color: "var(--status-critical)" }} aria-label="critical" />,
  warning: <TriangleAlert size={15} style={{ color: "var(--warning-ink)" }} aria-label="warning" />,
  good: <CheckCircle2 size={15} style={{ color: "var(--success-ink)" }} aria-label="good" />,
  info: <Info size={15} style={{ color: "var(--accent-ink)" }} aria-label="info" />,
};

export function InsightsList({ compact = false }: { compact?: boolean }) {
  const { previousVisit } = useAuth();
  const q = useInsights(previousVisit);
  if (q.isLoading) return <Loading height={compact ? 80 : 160} />;
  if (q.error && !q.data) return <ErrorState error={q.error} retry={() => void q.refetch()} />;
  const data = q.data!;
  const heading = data.first_visit ? "In the last 24 hours" : `Since your last visit (${ago(data.since)})`;
  return (
    <div>
      <div className="subtle" style={{ fontWeight: 600, marginBottom: 6 }}>
        {heading}
      </div>
      {data.items.length === 0 ? (
        <Empty title="Nothing new">No alerts, model changes or drift since then.</Empty>
      ) : (
        <ul className="insights">
          {data.items.map((i) => (
            <li key={i.kind}>
              {ICON[i.tone]}
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600 }}>{i.link ? <Link to={i.link}>{i.title}</Link> : i.title}</div>
                <div className="subtle">{i.detail}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
