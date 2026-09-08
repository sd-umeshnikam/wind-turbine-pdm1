# ADR-0003: Digital Twin Scope

## Status
Accepted

## Context
"Digital twin" is an overloaded term ranging from a live-data dashboard with a 3D model to a full physics/CFD simulation that mirrors structural and aerodynamic behavior. This platform needs a concrete, buildable scope, stated up front so expectations match what's actually delivered.

## Decision

The digital twin in this platform is a **live-data-bound visual and parametric model**, not a physics simulation:

- A 3D representation of a turbine (nacelle, rotor, blades, tower) rendered with react-three-fiber, driven by real-time telemetry from `digital-twin-service` (pitch angle rotates the blade meshes, rotor speed drives rotation animation, component health scores drive color overlays — green/amber/red per component: Gearbox/Hydraulics/Pitch System/Generator/Transformer/Rotor Brake/Bearing).
- A historical "replay" mode that re-plays a real labeled event's lead-up window (reusing the same data and methodology as `eda/scripts/04_degradation_trends.py`) so an engineer can see how a past fault actually developed, not a hypothetical simulation of one.
- Parametric, not simulated: the model reflects reported sensor state, it does not compute physical behavior (loads, stresses, fatigue) the way a structural/CFD twin would.

**Explicitly out of scope for this platform:** aerodynamic or structural simulation, predictive physics modeling of component wear, and any claim that the visual model's internal state is derived from anything other than the same sensor data already flowing through the medallion pipeline.

## Consequences
- The "twin" is buildable with the existing data and services — it adds a visualization and subscription layer on `digital-twin-service`, not a new simulation engine or physics team.
- If a genuine physics-based twin is wanted later (e.g., for structural fatigue prediction), that is a distinct, much larger initiative requiring turbine CAD/engineering models this dataset does not contain — it would sit alongside this visualization layer, not replace it.
- Marketing/stakeholder communication about the "digital twin" feature should use this scope, to avoid setting an expectation of physics-simulation capability the platform does not have.
