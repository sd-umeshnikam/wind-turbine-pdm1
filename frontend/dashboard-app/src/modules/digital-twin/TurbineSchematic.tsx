import type { ComponentHealth } from "../../api/types";
import { HEALTH_COLORS } from "../../shared/theme";
import { STATUS_LABEL } from "./twinText";

interface TurbineSchematicProps {
  rotorSpeedRpm: number;
  health: ComponentHealth;
  selected: string | null;
  onSelect: (component: string | null) => void;
  paused: boolean;
}

// Side view, nacelle facing right. Same parts and colours as the 3D scene, for browsers without WebGL.
const PARTS: { name: string; base: string; shape: JSX.Element }[] = [
  { name: "Transformer", base: "#7d8790", shape: <rect x="168" y="290" width="44" height="40" rx="3" /> },
  { name: "Generator", base: "#5a6672", shape: <rect x="96" y="92" width="44" height="40" rx="3" /> },
  { name: "Rotor Brake", base: "#46515c", shape: <rect x="140" y="88" width="10" height="48" rx="2" /> },
  { name: "Gearbox", base: "#5a6672", shape: <rect x="150" y="92" width="48" height="40" rx="3" /> },
  { name: "Bearing", base: "#6b7783", shape: <rect x="198" y="96" width="28" height="32" rx="3" /> },
  { name: "Hydraulics", base: "#7d8790", shape: <rect x="140" y="78" width="40" height="12" rx="2" /> },
  { name: "Pitch System", base: "#3b6fa0", shape: <circle cx="238" cy="112" r="14" /> },
];

export function TurbineSchematic({ rotorSpeedRpm, health, selected, onSelect, paused }: TurbineSchematicProps) {
  const secondsPerTurn = rotorSpeedRpm > 0 ? 60 / rotorSpeedRpm : 0;

  return (
    <svg className="twin-schematic" viewBox="0 0 320 340" role="img" aria-label="Turbine diagram" onClick={() => onSelect(null)}>
      <polygon points="152,132 172,132 180,330 144,330" fill="#b0b4b8" />

      <g
        className="twin-schematic-rotor"
        style={{
          animationDuration: `${secondsPerTurn}s`,
          animationPlayState: paused || !secondsPerTurn ? "paused" : "running",
        }}
      >
        {[0, 120, 240].map((deg) => (
          <rect key={deg} x="235" y="22" width="6" height="90" rx="3" fill="#d4d7da" transform={`rotate(${deg} 238 112)`} />
        ))}
      </g>

      {PARTS.map(({ name, base, shape }) => {
        const status = health[name];
        const fill = !status || status === "green" ? base : HEALTH_COLORS[status];
        return (
          <g
            key={name}
            className={`twin-schematic-part${selected === name ? " selected" : ""}${status === "red" ? " fault" : ""}`}
            fill={fill}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(name);
            }}
          >
            <title>{`${name}: ${status ? STATUS_LABEL[status] : "No data"}`}</title>
            {shape}
          </g>
        );
      })}
    </svg>
  );
}
