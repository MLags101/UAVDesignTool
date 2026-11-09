# Supersonic jet UAV design (to Mach 2)

Conceptual and preliminary design tools for small jet UAVs (about 50–1000 kg)
flying up to Mach 2: 16 calculators in `Supersonic Tools/` and the `supersonic`
family in the optimization workbench. Everything is SI. Models refuse inputs above
Mach 2 instead of extrapolating.

Status: **engineering preview** (model `0.5.0-preview`). The physics is checked
against exact relations and published references (see [Validation](#validation));
the integrated vehicle model has not been compared with flight data.

## Calculators

| Calculator | Answers | Method |
| --- | --- | --- |
| Compressible Flow | Isentropic, normal/oblique shock, expansion and cone-flow properties | Exact relations (NACA Report 1135), Taylor–Maccoll |
| Supersonic Airfoil | Section lift, wave drag, best L/D | Ackeret linear theory; exact shock-expansion for diamonds |
| Supersonic Wing Aerodynamics | CL_alpha, K and aerodynamic centre from Mach 0.1 to 2; leading-edge regime | Helmbold/DATCOM subsonic; linear supersonic theory (delta-wing elliptic integral, Bonney tip loss); C1 transonic bridge |
| Mach Drag Build-up | CD0 vs Mach, drag-divergence Mach, L/D max | Raymer component build-up with compressible friction and roughness cut-off; Lock/Korn drag rise; Sears–Haack × E_WD (Raymer eq. 12.45) |
| Area Rule & Wave Drag | Area distribution vs Sears–Haack, wave drag, where to waist the fuselage | Eminton–Lord slender-body integral on normal cuts; optional CSV input |
| Supersonic Inlet Design | Optimum ramp angles, recovery, capture area | Oblique + terminal normal shocks, Oswatitsch equal-strength optimum, MIL-E-5007D reference |
| Jet Engine Cycle | Thrust, fuel flow, TSFC and lapse vs Mach and altitude, dry and afterburning | Mattingly single-spool turbojet off-design analysis with throttle-ratio control |
| Jet Constraint Diagram | Required T/W vs W/S; driving requirement | Mattingly master equation with the engine's own lapse and Mach-dependent drag |
| Specific Excess Power & Energy Climb | Ps map, minimum-time/fuel climb, transonic pinch | Ps = V(T − D)/W; Rutowski energy method |
| Supersonic Range & Cruise | Specific range vs Mach and altitude, cruise range on a fuel load | Stepwise Breguet with part-power fuel flow from the cycle |
| Flight Envelope | Mach–altitude limits and what sets each | Stall, Ps = 0, q_max, skin temperature, Mach 2 ceiling |
| Aerothermal Skin Temperature | Stagnation, recovery and equilibrium skin temperature, soak time, material check | Eckert reference temperature + Reynolds analogy, radiation, lumped thin skin |
| Sonic Boom | Ground overpressure, signature duration, cut-off Mach | Whitham F-function → far-field N-wave (basis of Carlson, NASA TP-1122) |
| Supersonic Static Stability | Neutral point, static margin and C_n_beta vs Mach | Wing–tail summation, Munk body moment, Mach-dependent slopes |
| Panel Flutter Screening | Flutter parameter, margin, minimum skin thickness | Piston theory, λ_cr = 512 (simply supported) / 636 (clamped) |
| Jet UAV Weight Estimate | Takeoff-mass closure, breakdown, fuel volume | Physical build-up: areal-mass skins, bending/stiffness-sized spar, engine T/W |

All jet calculators share one description of the aircraft (wing, body, tails,
inlet, engine), so the same values can be typed into each form. Defaults describe
a representative 100 kg-class Mach 1.6–2 UAV.

## Design study family `supersonic`

`template("supersonic")` (or **Supersonic jet** in the Optimization workspace,
or `new_study(family="supersonic")` over MCP) builds a Mach 1.6 dash mission:
runway takeoff, climb to cruise altitude, transonic acceleration, 5 min supersonic
dash, 15 min Mach 0.85 return, descent.

**Requirements workflow.** The mission is flown with the configuration's
Mach-dependent drag and the turbojet cycle. Engine sea-level static thrust is
sized by the most demanding mission point — cruise drag, or climb/acceleration
with `min_excess_power` in hand — times `thrust_margin`. Fuel is the mission burn
over (1 − reserve) times `storage_margin`. Takeoff mass, thrust, fuel and inlet
capture area close together. `installed_thrust` and `fuel_mass` are outputs.

**Hardware workflow.** Supply a `jet_engine` (cycle values or a measured deck)
and `tank` components; the mission is flown as installed and the margins show
what is short.

| Component kind | Properties |
| --- | --- |
| `jet_engine` | `sls_thrust` (N, dry, per engine) plus optional `pressure_ratio`, `turbine_temperature`, `tt7_max`, `afterburner`; **or** `deck`: `[{mach, altitude, max_thrust, tsfc}]` on a complete grid. Mass is the installed engine. |
| `tank` | `fuel_mass` (kg per tank); mass is the empty tank |
| `wing` | optional `area`, `aspect_ratio`; mass replaces the estimate |

**Mission segments** may give Mach directly (`mach`, `end_mach`):

| Kind | Behaviour |
| --- | --- |
| `takeoff` | Ground roll to 1.2 V_stall at full dry thrust; `duration` is run-up time |
| `launch` | Catapult/booster: sets Mach and altitude, no fuel |
| `climb` | To `end_altitude` (default `cruise_altitude`) and `end_mach`, energy-integrated; duration ignored |
| `accelerate` | At the current altitude to `end_mach` (default `cruise_mach`); duration ignored |
| `cruise` | Steady, part-power. No Mach and speed 0 → design `cruise_mach`/`cruise_altitude`; altitude 0 on other cruise segments holds the current altitude |
| `descent` | Idle fuel to `end_altitude` over `duration` |

**Design parameters:** `payload`, `wing_area`, `aspect_ratio`, `le_sweep`,
`taper`, `thickness_ratio`, `body_length`, `body_diameter`, `tail_area`,
`vtail_area`, `tail_arm`, `cruise_mach`, `cruise_altitude`, `pressure_ratio`,
`turbine_temperature`, `cg_position`, plus `thrust_margin`, `storage_margin` and
`structure_margin`.

**Intrinsic margins** (all must be ≥ 0 for feasibility): fuel, fuel volume, cruise
thrust, excess power on climbs and accelerations, dynamic pressure,
skin temperature against `skin_temperature_limit`, subsonic static margin ≥
`min_static_margin`, supersonic static margin ≤ `max_static_margin`, and positive
directional stability at top speed.

**Metrics** include `takeoff_mass`, `installed_thrust`, `thrust_to_weight`,
`wing_loading`, `fuel_used`, `fuel_capacity`, `fuel_volume_margin`, `range`,
`mission_time`, `max_mach`, `supersonic_lift_to_drag`, `wave_drag_coefficient`,
`transonic_excess_power`, `time_to_climb`, `acceleration_time`,
`sustained_load_factor`, `takeoff_distance`, `landing_speed`, `static_margin`,
`static_margin_supersonic`, `directional_stability`, `max_skin_temperature`,
`max_dynamic_pressure` and `sonic_boom_overpressure` (reported, not constrained by
default).

Technology assumptions (drag efficiency `e_wd`, leading-edge suction, engine
component efficiencies, areal masses, engine T/W, fuel fractions, limits) are in
`vehicle.assumptions` and can be swept with `uncertainty_analysis`.

## What the models teach

* **Small supersonic aircraft are drag-dominated at low altitude.** At Mach 1.6 and
  11 km a 100 kg UAV with 850 N/m² wing loading flies at CL ≈ 0.02 and L/D ≈ 1;
  best L/D needs roughly ten times the dynamic-pressure-matched wing loading. The
  optimizer responds by flying higher on a smaller wing.
* **Fuel volume binds early.** Thin (3–5%) wings hold little; the fuselage carries
  most of the fuel.
* **The transonic pinch** sets thrust for many missions: check Ps through Mach 1.
* **Heating at Mach 2** (~100 °C recovery in the stratosphere) rules out
  room-temperature-cure composites and 3D-printed skins.
* **Directional stability falls** as the fin's lift slope drops with 1/β.

## Limits

* Mach 0.9–1.2 aerodynamics are a faired interpolation, flagged in results.
* Wave drag uses normal cuts and Raymer's empirical E_WD; the calculators' area-rule
  integral is a diagnostic, not used by the optimizer.
* Turbojet only (no turbofan or ramjet); afterburner modelled as a simple reheat.
  Installation losses beyond inlet recovery and nozzle expansion are in `cd_misc`.
* No trim drag, flutter of lifting surfaces, inlet unstart or buzz, or dynamic stability.
* Weights are a physical build-up calibrated by areal masses, not statistical fits.
* Sonic boom: steady level flight, no winds, no ray-tube amplification.

## Validation

Pinned by `tests/test_supersonic.py`:

| Check | Reference | Agreement |
| --- | --- | --- |
| Isentropic, normal and oblique shock at Mach 2, Prandtl–Meyer, θ_max | NACA Report 1135 | ≤ 1e-4 |
| Cone shock angle, Mach 2, 20° | NACA Report 1135 cone charts | within 0.3° |
| Wave drag of a Sears–Haack body (201 stations) | Analytic 9π/2 (A/l)² | 0.25% |
| Linear vs shock-expansion diamond airfoil | Exact theory | < 3% |
| Rectangular-wing lift slope | Bonney 4/β (1 − 1/(2Aβ)) | exact |
| Delta wing, sonic leading edge / slender limit | CL_α = A; Jones πA/2 | exact / 0.1% |
| Normal-shock and single-ramp optimum recovery at Mach 2 | Exact (0.721) / textbook (≈ 0.90) | exact / 1% |
| Turbojet scaling and model-turbine SLS performance | Linear scaling; small commercial turbojets | exact / plausibility band |
| Concorde ground boom, Mach 2, 16.5 km | ~93 Pa measured | ≈ 104 Pa (within 20%) |
| Boom altitude scaling | h^(−3/4) √(p_v) | exact |
| Requirements-to-hardware forward equivalence | Same design locked as hardware | < 1e-4 |

Not yet validated: whole-aircraft drag polars against published aircraft data, the
cycle model against a measured engine deck, and the transonic fairing. The panel
flutter critical values (512 / 636) and Raymer's E_WD Mach coefficient should be
confirmed against your reference editions before relying on them.
