# Aerospace optimization workbench

The Optimization sidebar page is an **engineering preview**. Software regression
tests pass, but full external vehicle validation and clean-machine release
qualification are separate gates. See [qualification](optimization-validation.md)
and [methods/reference specification](optimization-methods.md).

## Run

Use Python 3.12 on Windows x64. Install `requirements-windows.txt` for the pinned
desktop/build environment, or `requirements.txt` for source use. Start
`python UAVDesignTool.py`, open a project, and select **Optimization**.

1. Select the vehicle family, workflow and propulsion, then **Load new template**.
2. Edit fixed vehicle inputs. Inputs marked Variable are edited in tab 4.
3. Enter mission segments and requirements. Speeds/altitudes use SI; aircraft
   `cruise_speed` controls cruise segments. Other segment speeds remain explicit.
4. Inspect technology assumptions. For hardware-first studies, enter installed
   components and remove their owned properties from the variable list.
5. Choose objectives, bounds, solver, budget and seed. **Local refinement**
   holds integer choices fixed after the global search and polishes the
   continuous variables with SLSQP, using part of the same evaluation budget.
   It applies to a single objective. Run the baseline before optimization.
   Multiple objectives automatically use NSGA-II.
6. Inspect feasibility, margins and model warnings. Select a candidate to see its
   history/plots. Applying it previews project parameter changes and resets stage
   review. No run automatically applies its design.

Studies require **Save study** to save editor changes. Running saves the study
first. **Duplicate** creates a separate study. Runs are immutable snapshots; open
saved runs to inspect earlier designs or use the comparison table. A changed
study or imported data file cannot apply an older result as current.

## Two workflows

Requirements-first sizing closes airframe/structural mass, installed power and
energy/fuel storage. Default objective is minimum takeoff mass. Requirements and
technology assumptions define the problem; templates are not measured hardware.
Installed power and energy/fuel capacities are derived outputs, not free sizing
variables. To optimize endurance against a mass ceiling, add `mission_duration`
(seconds) as a free variable, maximize endurance and constrain `takeoff_mass`.
That variable scales the complete prescribed mission, including transitions.
Sizing variables `storage_margin`, `power_margin`, and (winged vehicles)
`structure_margin` let robust studies buy additional capacity and structure.
Scenario checks retain the resulting hardware and airframe instead of resizing
the vehicle separately for each scenario.

Hardware-first locks supplied components, quantities and ratings. Free variables
can still include geometry, payload, mission speed and `component.ID.position`.
Default objective is maximum endurance (rocket: maximum apogee). An empty hardware
template intentionally fails validation until actual parts are supplied. All-fixed
studies perform a single analysis without calling a numerical solver.

## Hardware records

Every record has `id`, `kind`, per-item `mass` (kg), `quantity`, `position` (m),
`properties` and `source`. Preserve the datum consistently: aircraft positions are
relative to wing leading edge; rocket positions run from nose toward tail.
The following properties are SI JSON values; curves are ordered `[x, y]` pairs.

| Kind | Required properties |
|---|---|
| motor | `max_power` (shaft W); quantity counts installed motors |
| controller | `max_current` (A per controller) |
| battery | One aggregate pack: `energy` (J), `voltage` (V), `resistance` (ohm), `min_voltage` (V), `max_current` (A); mass includes the pack |
| propeller | `diameter` (m); winged flight also requires `efficiency_map` (airspeed m/s → efficiency) and `max_power_map` (airspeed m/s → available shaft W) |
| engine | One aggregate engine/drivetrain: `max_power` (W), `fuel_flow_map` (total shaft W → kg/s) |
| tank | `fuel_mass` (kg per tank); component mass is the empty tank mass |
| main_rotor / lift_rotor | `diameter` (m), `chord` (m), `blades` (integer), `rpm`; rotor quantity must match topology |
| tail_rotor | `diameter` (m) |
| transmission | `max_power` (W) |
| lift_motor | `max_power` (W per motor), separate from cruise drive |
| wing | `area` (m²), `aspect_ratio`, `spar_cap_area` (m², per cap), `spar_depth` (m); supplied mass replaces estimated wing mass, supplied spar dimensions are checked without resizing |
| frame | `arm_length`, `arm_diameter`, `arm_wall` (m); supplied mass replaces estimated arm mass |
| rocket_motor | Dry component mass; `thrust_curve` (seconds → N), `propellant_curve` (seconds → remaining kg), matching time domains starting at zero |
| aerodynamics (rocket) | `cd_mach` (Mach → CD), `cp_mach` (Mach → CP distance from nose, m) |

Power maps represent the combined installed motor/propeller operating envelope,
not unconstrained static thrust. This legacy path uses a declared motor efficiency
and is labelled approximate. Source data must cover every requested operating point.

For coupled measured electric-drive analysis, supply motor `kv_rpm_per_volt`,
`resistance`, `no_load_current`, `max_current`, `max_power`, and `max_rpm`;
controller `efficiency` and `max_motor_current`; and propeller `performance_map`.
The motor values must use a consistent DC-equivalent terminal convention, not
unconverted BLDC phase resistance. Each propeller map entry is
`{"rpm":5000,"points":[[J,CT,CP],...]}`. At least two RPM slices and two advance-ratio
points per slice are required. Matching motor/controller/propeller quantities
represent identical parallel drives. The model solves the propeller load and
motor terminal voltage/current, then checks battery sag and controller limits.
No RPM or advance-ratio extrapolation is permitted. Supported map uses are
fixed-wing/VTOL cruise and multirotor axial hover/climb; edgewise multirotor flight
requires different data and is rejected. Helicopter motor constants can instead
use a transmission `motor_to_rotor_ratio` with the computed rotor shaft load.

Optional battery `ocv_map` (SOC fraction → volts) and `resistance_map` (SOC → ohms)
replace declared voltage/discharge approximations. Their domains must cover the
entire mission and endurance extension. These electrical models do not infer
unprovided thermal limits or temperature-dependent data.

**Import SI performance curve** copies a CSV into the project, records its SHA256,
and embeds its values in the selected component. Required CSV header is `x,y`.
Malformed rows, duplicate x values, NaN and extrapolation are rejected. The user
chooses the property and is responsible for supplying its documented SI units.
The coefficient-map CSV format is `rpm,J,CT,CP`; the other maps use `x,y`.

Endurance is simulated by extending the longest cruise, hover or manual-power
segment while keeping the other mission segments, installed hardware and sized
airframe fixed. The solver brackets the feasible duration against reserve,
electrical and other intrinsic limits. `endurance_history` and `endurance_limit`
record this separate simulation. Missing extendable segments make endurance
unavailable; reaching a model-data boundary is an invalid evaluation, not a
physical endurance limit. `endurance_time_limit` is a declared numerical bound
(default one day, maximum seven days), not a promised endurance.

## Trade studies

The specification box in Run accepts:

```json
{"kind":"grid","axes":{"wing_area":[0.5,0.7,0.9],"aspect_ratio":[6,8,10]}}
```

```json
{"kind":"latin_hypercube","samples":40,"seed":42}
```

```json
{"samples":100,"seed":42,"inputs":{"cd0":{"distribution":"uniform","lower":0.03,"upper":0.04}}}
```

Uncertainty inputs are technology assumptions. Normal distributions require
`mean` and `std`. Invalid samples remain counted; sampled feasibility is not a
certified probability. Sensitivity reports metric derivatives with respect to
continuous free variables. Scenario robustness holds the sized propulsion and
energy stores fixed and checks every prescribed scenario; reported metrics are
nominal, with worst-case objective values/margins and limiting-scenario names.

## Python API

```python
from uavlib.optimization import template, evaluate, optimize, Objective, Requirement
study = template("fixed_wing")
study.requirements += [Requirement("stall_speed", 11, "<=", scale=11)]
study.max_evaluations = 200
baseline = evaluate(study)
result = optimize(study, progress=lambda row: print(row["evaluation"]))
```

Other APIs: `sweep`, `sensitivity`, `assess_uncertainty`; dataclasses serialize
through `to_dict` / `StudyDefinition.from_dict`. `register_model` accepts an
object exposing `parameters`, `metrics`, and `evaluate(study, parameters)`.
The numerical API never imports PyQt. Legacy tool scripts retain their existing
interfaces. `examples/optimization_studies.py` exercises every built-in family.

Export writes JSON, candidate CSV and a Python runner. The exported runner requires
the matching `uavlib` source/package and numerical dependencies; JSON is not a
self-contained replacement for that runtime.

## Optional independent comparisons

`uavlib.optimization.adapters.compare(backend, study, candidate, config)` supports:

- `aerosandbox`: rectangular main-wing AeroBuildup comparison; specify `airfoil`,
  `alpha_degrees`, and optional `altitude`. Does not validate complete-aircraft trim.
- `openvsp`: specify `model_path`, `working_directory`, `parameter_bindings`
  (study design ID → VSP parameter ID or `{id,scale,offset}`), optional `double_inputs`, `integer_inputs`,
  `result_type`, `result_fields`, and version. Requires a prepared VSP model and
  a compatible installed API/VSPAERO. Never edits the source geometry file.
- `rocketpy`: specify complete `environment`, `motor` (GenericMotor), `rocket`,
  `motor_position`, `flight`, and optionally `nose`, `fins`, `parachute` keyword
  dictionaries. Geometry, inertia and coordinate conventions must explicitly
  match the selected candidate. No unmeasured inertia is invented.

Run comparisons in an external Python environment so optional tools cannot change
the pinned core dependencies. The worker file protocol supports `mode: compare`
with `backend`, `candidate`, and `config`. Results include backend version,
configuration, input hash and differences; they never overwrite core predictions.

The desktop **External comparison…** action asks for a backend, its configuration
JSON, and a Python executable with that backend and matching `uavlib` installed.
It evaluates the selected run snapshot, independently of current editor changes.
Records in `Optimization/comparisons/` retain the exact study, candidate, source
run, backend settings and returned comparison. They do not replace the selected
core design. OpenVSP 3.52.1 has been exercised with its Windows Python 3.13 API;
use its matching interpreter separately from the core Python 3.12 environment.
Optional `vspaero_path` selects its solver directory and `geometry_integer_inputs`
configures geometry analysis sets. The adapter checks parameter bindings after
geometry updates and runs against a copied candidate geometry in the working folder.

## Persistence, reporting and interruption

Project JSON v3 stores study/run references. Loading v1/v2 is read-only until the
next save, which first preserves the old JSON as `.v2.bak`. Newer unsupported
schemas are refused. Study/data/run paths remain within the project folder.

Workers write progress to `Optimization/pending/<id>/progress.jsonl` and full
completed evaluations, including mission histories, to `evaluations.jsonl`.
Every full record is flushed and fsynced before the next evaluation starts.
Cancellation is cooperative between evaluations and enforced after three seconds
in the GUI. Optimization, sweeps, uncertainty and sensitivity all support it.
The GUI recovers completed evaluations after forced termination; after restarting
the app, use **Recover interrupted run** and select its pending directory.
The headless equivalent is `uavlib.optimization.worker.recover(folder)` after the
worker exits. Recovery requires the original model version and unchanged request.
An incomplete final journal record is ignored; corrupt completed records cause
an explicit error. Recovered runs have `interrupted` status, never solver success.
Incomplete sensitivity pairs are retained but do not produce derivatives.

Uncertainty first resolves the nominal design, then holds installed power, storage
and sized airframe fixed while sampling assumptions. Each evaluation records its
`sampled_inputs`. Sampled feasibility uses the number actually completed, including
invalid samples; a cancelled assessment with no samples has no feasibility estimate.

The helicopter solves main-disk attitude, collective/cyclic harmonics and tail
thrust for six-component steady rigid-aircraft force/moment equilibrium, including
hub/tail offsets and main-rotor reaction torque. Histories expose the residuals.
The uniform-inflow rotor has no flapping model, and its published hover collective
comparison currently fails the predeclared accuracy gate; see qualification.
Reverse-flow and negative axial-inflow elements are rejected. Transition histories expose axial/vertical force residuals, cruise
thrust, lift-system thrust and required braking tilt. The declared
`transition_tilt_limit` is in radians (template: 20 degrees). Setting it to zero
prohibits lift-system braking tilt. These planar force checks do not establish
moment equilibrium or dynamic controllability. Transition endpoint altitudes
determine climb rate when supplied.

Reports include applied study fingerprints, model version, assumptions, margins
and warnings for selected stages. Missing applied-run provenance stops export
with an actionable error rather than silently producing an incomplete report.

Build with `pyinstaller UAVDesignTool.spec`. Execute the release smoke test using
`python tests/check_frozen_optimization.py path/to/UAVDesignTool.exe`.
