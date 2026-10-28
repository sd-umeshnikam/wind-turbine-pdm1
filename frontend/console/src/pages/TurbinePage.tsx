import { Link, useParams, useSearchParams } from "react-router-dom";
import { useTurbine } from "../api/hooks";
import { ApiError } from "../api/client";
import { Badge, Banner, Empty, ErrorState, HealthBadge, Loading, PageHead, SeverityBadge, Tabs } from "../components/ui";
import { dataTime, num, pct } from "../lib/format";
import { EventsTab } from "./turbine/EventsTab";
import { ExpectedTab } from "./turbine/ExpectedTab";
import { OverviewTab } from "./turbine/OverviewTab";
import { SensorsTab } from "./turbine/SensorsTab";
import { TrendsTab } from "./turbine/TrendsTab";
import { TwinTab } from "./turbine/TwinTab";

const TABS = [
  { id: "overview", label: "Components" },
  { id: "trends", label: "Health trends" },
  { id: "expected", label: "Expected vs actual" },
  { id: "sensors", label: "Sensor explorer" },
  { id: "twin", label: "Digital twin" },
  { id: "events", label: "Labelled events" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export function TurbinePage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "overview") as TabId;
  const turbine = useTurbine(id);

  const setTab = (next: TabId, extra: Record<string, string> = {}) =>
    setParams({ tab: next, ...extra }, { replace: true });

  if (turbine.isLoading) return <Loading height={320} />;
  if (turbine.error && !turbine.data) {
    if (turbine.error instanceof ApiError && turbine.error.status === 404)
      return <Empty title={`No turbine ${id}`}><Link to="/turbines">Back to turbines</Link></Empty>;
    return <ErrorState error={turbine.error} retry={() => void turbine.refetch()} />;
  }
  const t = turbine.data!;
  const replay = t.replay;

  return (
    <>
      <PageHead
        crumbs={
          <>
            <Link to="/turbines">Turbines</Link> / Farm {t.farm_id}
          </>
        }
        title={
          <span className="row" style={{ gap: 10 }}>
            {t.name} <HealthBadge health={t.health} />
            {t.alarm && <Badge tone="critical">Detector in alarm</Badge>}
          </span>
        }
        lede={
          <>
            {replay?.cursor_ts ? <>Replay position {dataTime(replay.cursor_ts)}</> : "Replay has not started"}
            {replay?.operating_status_label && <> · {replay.operating_status_label}</>}
            {replay && <> · {pct(replay.progress, 0)} through cycle {replay.cycle + 1}</>}
            {t.model_version && <> · scored by {t.model_version}</>}
            {t.anomaly_score !== null && <> · detector score {num(t.anomaly_score, 2)}</>}
          </>
        }
      />
      {t.active_alert && (
        <Banner tone="warn">
          <span className="row" style={{ gap: 8 }}>
            <SeverityBadge severity={t.active_alert.severity} />
            <Link to={`/alerts?id=${t.active_alert.id}`}>{t.active_alert.title}</Link>
            <span className="subtle">
              {t.active_alert.status} · {t.active_alert.condition_active ? "condition still present" : "condition cleared"}
            </span>
          </span>
        </Banner>
      )}
      <Tabs tabs={[...TABS]} value={tab} onChange={(next) => setTab(next)} />
      {tab === "overview" && (
        <OverviewTab
          turbine={t}
          focus={params.get("component")}
          onSensor={(sensor) => setTab("expected", { sensor })}
        />
      )}
      {tab === "trends" && <TrendsTab turbine={t} />}
      {tab === "expected" && <ExpectedTab turbine={t} initialSensor={params.get("sensor")} />}
      {tab === "sensors" && <SensorsTab turbine={t} />}
      {tab === "twin" && <TwinTab turbine={t} onComponent={(c) => setTab("overview", { component: c })} />}
      {tab === "events" && <EventsTab turbine={t} />}
    </>
  );
}
