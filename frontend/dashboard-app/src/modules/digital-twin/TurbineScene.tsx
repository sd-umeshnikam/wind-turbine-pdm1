import { useRef, useState, type ReactNode } from "react";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import type { Group, MeshStandardMaterial } from "three";
import type { ComponentHealth, HealthStatus } from "../../api/types";
import { HEALTH_COLORS } from "../../shared/theme";
import { STATUS_LABEL } from "./twinText";

interface TurbineSceneProps {
  rotorSpeedRpm: number;
  pitchAngleDeg: number;
  health: ComponentHealth;
  selected: string | null;
  onSelect: (component: string | null) => void;
  paused: boolean;
}

const BLADE_COUNT = 3;
const BLADE_LENGTH = 3.2;
const TOWER_HEIGHT = 5;
const NACELLE_Y = TOWER_HEIGHT + 0.15;
// Model is shifted down by this so OrbitControls' default origin target sits at its middle.
const MODEL_CENTER_Y = (NACELLE_Y + BLADE_LENGTH + 0.5) / 2;

interface PartProps {
  name: string;
  status: HealthStatus | undefined;
  baseColor: string;
  position: [number, number, number];
  rotation?: [number, number, number];
  selected: boolean;
  hovered: boolean;
  onHover: (name: string | null) => void;
  onSelect: (name: string) => void;
  children: ReactNode;
}

function Part({ name, status, baseColor, position, rotation, selected, hovered, onHover, onSelect, children }: PartProps) {
  const materialRef = useRef<MeshStandardMaterial>(null);
  const color = !status || status === "green" ? baseColor : HEALTH_COLORS[status];

  useFrame(({ clock }) => {
    const m = materialRef.current;
    if (!m) return;
    const pulse = status === "red" ? 0.35 + 0.3 * Math.sin(clock.elapsedTime * 5) : 0;
    m.emissiveIntensity = Math.max(pulse, selected || hovered ? 0.45 : 0);
  });

  return (
    <group position={position} rotation={rotation}>
      <mesh
        onClick={(e: ThreeEvent<MouseEvent>) => {
          e.stopPropagation();
          onSelect(name);
        }}
        onPointerOver={(e: ThreeEvent<PointerEvent>) => {
          e.stopPropagation();
          onHover(name);
          document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => {
          onHover(null);
          document.body.style.cursor = "";
        }}
      >
        {children}
        <meshStandardMaterial
          ref={materialRef}
          color={color}
          emissive={status === "red" ? HEALTH_COLORS.red : "#ffffff"}
          emissiveIntensity={0}
        />
      </mesh>
      {(selected || hovered) && (
        <Html center position={[0, 0.55, 0]} style={{ pointerEvents: "none" }}>
          <div className="twin-label">
            <strong>{name}</strong>
            <span style={{ color: status ? HEALTH_COLORS[status] : undefined }}>
              {status ? STATUS_LABEL[status] : "No data"}
            </span>
          </div>
        </Html>
      )}
    </group>
  );
}

function Blade({ angle, pitchRad }: { angle: number; pitchRad: number }) {
  return (
    <group rotation={[0, 0, angle]}>
      {/* pitch rotation is around the blade's own long axis */}
      <group rotation={[pitchRad, 0, 0]} position={[0, 0.5, 0]}>
        <mesh position={[0, BLADE_LENGTH / 2, 0]}>
          <boxGeometry args={[0.18, BLADE_LENGTH, 0.05]} />
          <meshStandardMaterial color="#e8e8e8" />
        </mesh>
      </group>
    </group>
  );
}

export function TurbineScene({ rotorSpeedRpm, pitchAngleDeg, health, selected, onSelect, paused }: TurbineSceneProps) {
  const rotorRef = useRef<Group>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const pitchRad = (pitchAngleDeg * Math.PI) / 180;

  useFrame((_, delta) => {
    if (!rotorRef.current || paused) return;
    rotorRef.current.rotation.z += ((rotorSpeedRpm * 2 * Math.PI) / 60) * delta;
  });

  const partProps = (name: string) => ({
    name,
    status: health[name],
    selected: selected === name,
    hovered: hovered === name,
    onHover: setHovered,
    onSelect,
  });

  return (
    <>
      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 8, 5]} intensity={1.1} />

      <group position={[0, -MODEL_CENTER_Y, 0]}>
        {/* Clicking empty space on the tower clears the selection */}
        <mesh position={[0, TOWER_HEIGHT / 2, 0]} onClick={() => onSelect(null)}>
          <cylinderGeometry args={[0.25, 0.4, TOWER_HEIGHT, 16]} />
          <meshStandardMaterial color="#b0b4b8" />
        </mesh>

        <Part {...partProps("Transformer")} baseColor="#7d8790" position={[0.95, 0.4, 0]}>
          <boxGeometry args={[0.65, 0.8, 0.65]} />
        </Part>

        {/* Nacelle, split front-to-back into the drivetrain parts it houses */}
        <Part {...partProps("Bearing")} baseColor="#6b7783" position={[0, NACELLE_Y, 0.93]}>
          <boxGeometry args={[0.55, 0.5, 0.34]} />
        </Part>
        <Part {...partProps("Gearbox")} baseColor="#5a6672" position={[0, NACELLE_Y, 0.5]}>
          <boxGeometry args={[0.7, 0.6, 0.5]} />
        </Part>
        <Part {...partProps("Rotor Brake")} baseColor="#46515c" position={[0, NACELLE_Y, 0.2]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.27, 0.27, 0.09, 24]} />
        </Part>
        <Part {...partProps("Generator")} baseColor="#5a6672" position={[0, NACELLE_Y, -0.08]}>
          <boxGeometry args={[0.7, 0.6, 0.45]} />
        </Part>
        <Part {...partProps("Hydraulics")} baseColor="#7d8790" position={[0, NACELLE_Y + 0.38, 0.35]}>
          <boxGeometry args={[0.32, 0.16, 0.42]} />
        </Part>

        <group position={[0, NACELLE_Y, 1.15]}>
          <Part {...partProps("Pitch System")} baseColor="#3b6fa0" position={[0, 0, 0]}>
            <sphereGeometry args={[0.28, 16, 16]} />
          </Part>
          <group ref={rotorRef}>
            {Array.from({ length: BLADE_COUNT }, (_, i) => (
              <Blade key={i} angle={(i * 2 * Math.PI) / BLADE_COUNT} pitchRad={pitchRad} />
            ))}
          </group>
        </group>
      </group>
    </>
  );
}
