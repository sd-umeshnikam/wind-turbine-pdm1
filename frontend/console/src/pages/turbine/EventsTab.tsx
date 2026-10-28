import { useTurbineEvents } from "../../api/hooks";
import type { TurbineDetail } from "../../api/types";
import { Badge, Card, Empty, QueryView } from "../../components/ui";
import { dataDate, int, titleCase } from "../../lib/format";

export function EventsTab({ turbine }: { turbine: TurbineDetail }) {
  const events = useTurbineEvents(turbine.id);
  const current = turbine.replay?.source_event_id;
  return (
    <Card
      title="Labelled CARE events of this turbine"
      hint="each event = a year of normal history followed by a prediction window that leads into a known outcome"
      flush
    >
      <QueryView query={events} height={240}>
        {(list) =>
          list.length ? (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Event</th>
                    <th>Outcome</th>
                    <th>Component</th>
                    <th>Training history</th>
                    <th>Prediction window</th>
                    <th>Event</th>
                    <th className="num">Rows</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((e) => (
                    <tr key={e.id} className={e.source_event_id === current ? "selected" : undefined}>
                      <td>
                        #{e.source_event_id}
                        {e.source_event_id === current && (
                          <div>
                            <Badge tone="accent">replaying now</Badge>
                          </div>
                        )}
                      </td>
                      <td>
                        {e.label === "anomaly" ? <Badge tone="critical">Anomaly</Badge> : <Badge tone="good">Normal</Badge>}
                        {e.description && <div className="subtle" style={{ marginTop: 2 }}>{e.description}</div>}
                      </td>
                      <td>{e.component_code ? titleCase(e.component_code) : "—"}</td>
                      <td className="num" style={{ textAlign: "left" }}>
                        {dataDate(e.window_start)} → {dataDate(e.prediction_start)}
                      </td>
                      <td className="num" style={{ textAlign: "left" }}>
                        {dataDate(e.prediction_start)} → {dataDate(e.event_end)}
                      </td>
                      <td className="num" style={{ textAlign: "left" }}>
                        {dataDate(e.event_start)} → {dataDate(e.event_end)}
                      </td>
                      <td className="num">{int(e.n_rows)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="No labelled events for this turbine" />
          )
        }
      </QueryView>
    </Card>
  );
}
