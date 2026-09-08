import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { subscribeToTwinUpdates } from "../../api/client";
import type { TwinState } from "../../api/types";
import { HealthPill } from "../../shared/HealthPill";
import { TurbineScene } from "./TurbineScene";
import "./DigitalTwinPage.css";

export function DigitalTwinPage() {
  const { turbineId = "" } = useParams();
  const [state, setState] = useState<TwinState | null>(null);

  useEffect(() => {
    setState(null);
    const unsubscribe = subscribeToTwinUpdates(turbineId, setState);
    return unsubscribe;
  }, [turbineId]);

  return (
    <div className="digital-twin">
      <header className="module-header">
        <h1>Digital Twin - {turbineId}</h1>
        <p className="module-subtitle">
          Live-data-bound 3D visualization (ADR-0003 scope: reflects rotor speed, pitch angle and
          component health as they stream in - not a physics simulation).
        </p>
      </header>

      <div className="twin-viewport">
        <Canvas camera={{ position: [8, 4, 11], fov: 45 }}>
          <TurbineScene
            rotorSpeedRpm={state?.rotorSpeedRpm ?? 0}
            pitchAngleDeg={state?.pitchAngleDeg ?? 0}
          />
          {/* target left at the default [0,0,0] - TurbineScene recenters the
              model on the origin specifically so this stays centered.
              enableZoom (default true) drives both the mouse scroll wheel
              and two-finger pinch on touch; see .twin-viewport canvas's
              touch-action: none in CSS, required for the pinch gesture to
              reach three.js instead of the browser's native page zoom. */}
          <OrbitControls
            enablePan={false}
            enableZoom
            minDistance={5}
            maxDistance={22}
          />
        </Canvas>

        <div className="twin-overlay">
          <h2>Live state</h2>
          {!state ? (
            <p>Connecting…</p>
          ) : (
            <>
              <dl>
                <dt>Rotor speed</dt>
                <dd>{state.rotorSpeedRpm.toFixed(1)} rpm</dd>
                <dt>Pitch angle</dt>
                <dd>{state.pitchAngleDeg.toFixed(1)}°</dd>
              </dl>
              <h3>Component health</h3>
              <ul className="health-list">
                {Object.entries(state.componentHealth).map(([component, status]) => (
                  <li key={component}>
                    <span>{component}</span>
                    <HealthPill status={status} label={status} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
