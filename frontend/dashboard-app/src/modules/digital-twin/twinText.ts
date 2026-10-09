import type { HealthStatus } from "../../api/types";

export const STATUS_LABEL: Record<HealthStatus, string> = {
  green: "Healthy",
  amber: "Watch",
  red: "Fault",
};

export const COMPONENT_INFO: Record<string, { where: string; what: string }> = {
  Gearbox: {
    where: "Middle of the nacelle",
    what: "Speeds up the slow blade rotation for the generator. Watch for oil pressure or temperature drifting.",
  },
  Hydraulics: {
    where: "Unit on top of the nacelle",
    what: "Supplies pressure to the brakes and pitch. Watch for pressure falling or the pump running more often.",
  },
  "Pitch System": {
    where: "Blue hub at the front",
    what: "Turns each blade to the right angle for the wind. A blade that stops responding shuts the turbine down.",
  },
  Generator: {
    where: "Back of the nacelle",
    what: "Turns rotation into electricity. Bearing and winding wear usually shows as rising temperature.",
  },
  Transformer: {
    where: "Box at the tower base",
    what: "Steps the voltage up for the grid. Oil temperature is the best early warning.",
  },
  "Rotor Brake": {
    where: "Disc between gearbox and generator",
    what: "Holds the rotor still for maintenance. Low hydraulic pressure means it can't grip properly.",
  },
  Bearing: {
    where: "Front of the nacelle, behind the hub",
    what: "Carries the weight of the rotor and blades. Damage shows up in vibration before temperature.",
  },
};
