import type { HealthStatus } from "../../api/types";

export const STATUS_LABEL: Record<HealthStatus, string> = {
  green: "Healthy",
  amber: "Watch",
  red: "Fault",
};

export const COMPONENT_INFO: Record<string, { where: string; what: string }> = {
  Gearbox: {
    where: "Middle of the nacelle",
    what: "Speeds up rotation for the generator. Watch oil pressure and temperature.",
  },
  Hydraulics: {
    where: "Top of the nacelle",
    what: "Powers the brakes and pitch. Watch for falling pressure.",
  },
  "Pitch System": {
    where: "Hub",
    what: "Sets the blade angle. A stuck blade stops the turbine.",
  },
  Generator: {
    where: "Back of the nacelle",
    what: "Makes the electricity. Watch bearing temperature.",
  },
  Transformer: {
    where: "Tower base",
    what: "Steps up voltage for the grid. Watch oil temperature.",
  },
  "Rotor Brake": {
    where: "Between gearbox and generator",
    what: "Holds the rotor still. Needs hydraulic pressure to grip.",
  },
  Bearing: {
    where: "Front of the nacelle",
    what: "Carries the rotor. Damage shows in vibration first.",
  },
};
