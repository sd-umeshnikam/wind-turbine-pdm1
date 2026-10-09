import { Component, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { subscribeToTwinUpdates } from "../../api/client";
import type { HealthStatus, TwinState } from "../../api/types";
import { HealthPill } from "../../shared/HealthPill";
import { HEALTH_COLORS } from "../../shared/theme";
import { TurbineScene } from "./TurbineScene";
import { TurbineSchematic } from "./TurbineSchematic";
import { COMPONENT_INFO, STATUS_LABEL } from "./twinText";
import "./DigitalTwinPage.css";

const LEGEND: HealthStatus[] = ["green", "amber", "red"];

let webGLSupported: boolean | null = null;

// Probed once per page load; the probe context is released so it doesn't count against
// the browser's limit on live WebGL contexts (Chrome drops the oldest past ~16).
function browserSupportsWebGL(): boolean {
  if (webGLSupported === null) {
    try {
      const canvas = document.createElement("canvas");
      const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
      webGLSupported = !!gl;
      gl?.getExtension("WEBGL_lose_context")?.loseContext();
    } catch {
      webGLSupported = false;
    }
  }
  return webGLSupported;
}

// getContext can succeed while three.js still fails to start the renderer, so this catches that case too.
class WebGLBoundary extends Component<{ onFail: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onFail();
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

function HealthSummary({ health }: { health: Record<string, HealthStatus> }) {
  const entries = Object.entries(health);
  const faults = entries.filter(([, s]) => s === "red").map(([c]) => c);
  const watch = entries.filter(([, s]) => s === "amber").map(([c]) => c);
  const worst: HealthStatus = faults.length ? "red" : watch.length ? "amber" : "green";

  return (
    <div className="twin-summary" style={{ borderColor: HEALTH_COLORS[worst] }}>
      {worst === "green" ? (
        <strong>All {entries.length} parts are healthy</strong>
      ) : (
        <>
          <strong>
            {faults.length + watch.length} of {entries.length} parts need attention
          </strong>
          {faults.length > 0 && <span>Fault: {faults.join(", ")}</span>}
          {watch.length > 0 && <span>Watch: {watch.join(", ")}</span>}
        </>
      )}
    </div>
  );
}

export function DigitalTwinPage() {
  const { turbineId = "" } = useParams();
  const [state, setState] = useState<TwinState | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [viewKey, setViewKey] = useState(0);
  const [has3D, setHas3D] = useState(browserSupportsWebGL);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  useEffect(() => {
    setState(null);
    setSelected(null);
    return subscribeToTwinUpdates(turbineId, (next) => {
      if (!pausedRef.current) setState(next);
    });
  }, [turbineId]);

  const health = state?.componentHealth ?? {};
  const selectedStatus = selected ? health[selected] : undefined;
  const selectedInfo = selected ? COMPONENT_INFO[selected] : undefined;

  return (
    <div className="digital-twin">
      <header className="module-header">
        <h1>Digital Twin - {turbineId}</h1>
        <p className="module-subtitle">
          A live 3D view of this turbine. Each part is coloured by its health. Click a part, or a
          name in the list, to see what it does.
        </p>
        <nav className="twin-links">
          <Link to={`/assets/${turbineId}`}>Sensor history</Link>
          <Link to={`/forecasts/${turbineId}`}>Forecasts &amp; RUL</Link>
        </nav>
      </header>

      <div className="twin-layout">
        <div className="twin-viewport">
          {has3D ? (
            <WebGLBoundary onFail={() => setHas3D(false)}>
              {/* Remounting the canvas (viewKey) is what "Reset view" does: camera back to its start position. */}
              <Canvas key={viewKey} camera={{ position: [8, 4, 11], fov: 45 }} onPointerMissed={() => setSelected(null)}>
                <TurbineScene
                  rotorSpeedRpm={state?.rotorSpeedRpm ?? 0}
                  pitchAngleDeg={state?.pitchAngleDeg ?? 0}
                  health={health}
                  selected={selected}
                  onSelect={setSelected}
                  paused={paused}
                />
                <OrbitControls enablePan={false} enableZoom minDistance={5} maxDistance={22} />
              </Canvas>
            </WebGLBoundary>
          ) : (
            <TurbineSchematic
              rotorSpeedRpm={state?.rotorSpeedRpm ?? 0}
              health={health}
              selected={selected}
              onSelect={setSelected}
              paused={paused}
            />
          )}

          <div className="twin-toolbar">
            <button type="button" onClick={() => setPaused((p) => !p)}>
              {paused ? "Resume" : "Pause"}
            </button>
            {has3D && (
              <button type="button" onClick={() => setViewKey((k) => k + 1)}>
                Reset view
              </button>
            )}
          </div>

          <p className="twin-hint">
            {has3D
              ? "Drag to rotate · Scroll or pinch to zoom · Click a part for details"
              : "3D view needs graphics acceleration, so this is a 2D diagram. Click a part for details."}
          </p>

          <ul className="twin-legend" aria-label="Colour legend">
            {LEGEND.map((s) => (
              <li key={s}>
                <span className="swatch" style={{ background: s === "green" ? "#6b7783" : HEALTH_COLORS[s] }} />
                {STATUS_LABEL[s]}
              </li>
            ))}
          </ul>
        </div>

        <aside className="twin-panel">
          <div className="twin-status">
            <span className={paused ? "dot paused" : state ? "dot live" : "dot"} />
            {!state ? "Connecting…" : paused ? "Paused" : "Live"}
            {state && <span className="updated">Updated {new Date(state.timestamp).toLocaleTimeString()}</span>}
          </div>

          {state && (
            <>
              <HealthSummary health={health} />

              <div className="twin-readings">
                <div>
                  <span className="label">Rotor speed</span>
                  <span className="value">{state.rotorSpeedRpm.toFixed(1)} rpm</span>
                  <span className="help">How fast the blades turn</span>
                </div>
                <div>
                  <span className="label">Blade pitch</span>
                  <span className="value">{state.pitchAngleDeg.toFixed(1)}°</span>
                  <span className="help">Blade angle to the wind</span>
                </div>
              </div>

              <h2>Parts</h2>
              <ul className="twin-parts">
                {Object.entries(health).map(([component, status]) => (
                  <li key={component}>
                    <button
                      type="button"
                      className={component === selected ? "active" : ""}
                      onClick={() => setSelected(component === selected ? null : component)}
                    >
                      <span>{component}</span>
                      <HealthPill status={status} label={STATUS_LABEL[status]} />
                    </button>
                  </li>
                ))}
              </ul>

              {selected && selectedInfo && (
                <div className="twin-detail">
                  <h3>
                    {selected}
                    {selectedStatus && <HealthPill status={selectedStatus} label={STATUS_LABEL[selectedStatus]} />}
                  </h3>
                  <p className="where">{selectedInfo.where}</p>
                  <p>{selectedInfo.what}</p>
                  <Link to={`/forecasts/${turbineId}`}>See remaining life forecast →</Link>
                </div>
              )}
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
