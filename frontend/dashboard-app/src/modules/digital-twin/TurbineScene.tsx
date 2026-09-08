import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import type { Group, Mesh } from "three";

interface TurbineSceneProps {
  rotorSpeedRpm: number;
  pitchAngleDeg: number;
}

const BLADE_COUNT = 3;
const BLADE_LENGTH = 3.2;
const TOWER_HEIGHT = 5;
const NACELLE_Y = TOWER_HEIGHT + 0.15;
// Approximate vertical center of the model's bounding volume (tower base at
// world y=0 up to a blade tip at full reach, ~NACELLE_Y + BLADE_LENGTH+0.5).
// Everything below is rendered inside a group offset by -MODEL_CENTER_Y so
// the model is centered on the scene origin - which is what OrbitControls'
// default (and this page's) look-at target points at. Without this, the
// turbine's true center sits well above the origin and the top of the
// nacelle/blades gets clipped by the canvas edge instead of being centered.
const MODEL_CENTER_Y = (NACELLE_Y + BLADE_LENGTH + 0.5) / 2;

function Blade({ angle, pitchRad }: { angle: number; pitchRad: number }) {
  const ref = useRef<Mesh>(null);
  return (
    <group rotation={[0, 0, angle]}>
      {/* pitch rotation is around the blade's own long axis */}
      <group rotation={[pitchRad, 0, 0]} position={[0, 0.5, 0]}>
        <mesh ref={ref} position={[0, BLADE_LENGTH / 2, 0]}>
          <boxGeometry args={[0.18, BLADE_LENGTH, 0.05]} />
          <meshStandardMaterial color="#e8e8e8" />
        </mesh>
      </group>
    </group>
  );
}

export function TurbineScene({ rotorSpeedRpm, pitchAngleDeg }: TurbineSceneProps) {
  const rotorRef = useRef<Group>(null);
  const pitchRad = (pitchAngleDeg * Math.PI) / 180;

  useFrame((_, delta) => {
    if (!rotorRef.current) return;
    const radiansPerSecond = (rotorSpeedRpm * 2 * Math.PI) / 60;
    rotorRef.current.rotation.z += radiansPerSecond * delta;
  });

  return (
    <>
      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 8, 5]} intensity={1.1} />

      {/* Model recentered on the origin (see MODEL_CENTER_Y) so the default
          camera target actually looks at the turbine's middle, not its base. */}
      <group position={[0, -MODEL_CENTER_Y, 0]}>
        {/* Tower */}
        <mesh position={[0, TOWER_HEIGHT / 2, 0]}>
          <cylinderGeometry args={[0.25, 0.4, TOWER_HEIGHT, 16]} />
          <meshStandardMaterial color="#b0b4b8" />
        </mesh>

        {/* Nacelle */}
        <mesh position={[0, NACELLE_Y, 0.4]}>
          <boxGeometry args={[0.7, 0.6, 1.4]} />
          <meshStandardMaterial color="#5a6672" />
        </mesh>

        {/* Rotor hub + blades, mounted at the front of the nacelle */}
        <group position={[0, NACELLE_Y, 1.15]}>
          <mesh>
            <sphereGeometry args={[0.28, 16, 16]} />
            <meshStandardMaterial color="#3b6fa0" />
          </mesh>
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
