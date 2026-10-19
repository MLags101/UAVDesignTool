# Qualification status

Status: **engineering preview, not the fully qualified major release**.

## Verified in this workspace

- Original 70 physics/tool regressions retained.
- Expanded suite: 127 tests passing, including offscreen Qt integration.
- Analytical checks: atmosphere reference points, momentum-theory hover power,
  battery quadratic operating point and strict interpolation domains.
- Analytical rotor thrust/hub-moment equilibrium fixtures, symmetric hover cyclic
  controls, reverse-flow rejection and planar transition force balance.
- Durable full-evaluation journals, interrupted-run recovery, truncated-tail
  handling, corruption rejection, and cooperative cancellation of trade studies.
- Uncertainty holds nominal installed power/storage fixed and retains sampled inputs.
- Known constrained optimum with SLSQP; deterministic seeded integer search;
  feasible nondominated NSGA-II output; explicit cancellation and budget status.
- Requirements-to-hardware forward equivalence for fixed wing, multirotor,
  conventional helicopter, lift-plus-cruise and rocket configurations.
- Aircraft mass closure, fuel mass evolution, tail-rotor power, separate VTOL
  lift/cruise power and energy accounting, and scenario capacity preservation.
- Rocket ascent/apogee/recovery events, mass evolution and aerodynamic-domain
  rejection. These are numerical/model checks, not flight-data validation.
- v2 backup/v3 migration, future-version rejection, immutable snapshots,
  stale-result fingerprints, strict CSV import and portable relative paths.
- Qt study roundtrip, worker execution, saved-run reopening, design application
  with stage-review reset, and Overleaf provenance export.
- GUI recovery saves interrupted results as a run; external comparison results
  preserve the selected core result and store their own candidate provenance.
- Windows one-file build and isolated worker execution with Python-specific
  environment variables removed and PATH restricted to Windows System32:
  baseline, single-objective, Pareto and cooperative cancellation all passed.
- Real optional-adapter execution with AeroSandbox 4.2.10 and RocketPy 1.13.0.
  Synthetic smoke cases verify API integration; they do not validate every
  equation or vehicle family. Results are saved under build/adapter-validation.

Build fixes discovered by execution: startup exceptions must be caught before
GUI imports in worker mode; moocore distribution metadata must be included for
pymoo's hypervolume dependencies.

Latest local qualification: model `0.4.0-preview`, 2026-09-22. Python 3.12.14
ran 133 tests clean, including the offscreen Qt study roundtrip. The rebuilt
`dist/UAVDesignTool.exe` passed baseline, single-objective, Pareto and
cancellation smoke checks with Python removed from PATH. All five default
templates evaluate valid and feasible under their implemented checks.
Real AeroSandbox/RocketPy adapter smoke checks were repeated successfully.
The executable is `dist/optimization-preview/UAVDesignTool.exe`.

Additional 0.3 evidence:

- Coupled measured CT/CP maps, DC-equivalent motor circuit, controller ratings and
  battery voltage/current feasibility; UIUC propeller-point checks and circuit
  conservation tests. Optional SOC voltage/resistance maps reject extrapolation.
- Simulation-based endurance extends one cruise/hover segment while retaining
  other mission overhead, installed power/storage and structure. An analytical
  constant-load case and VTOL segment-preservation tests pass.
- Six-component steady rigid-helicopter equilibrium, including main reaction
  torque, tail side force, rotor attitude and hub/tail offsets; analytical residual
  fixtures pass. This does not validate blade loading or forward-flight accuracy.
- Real OpenVSP 3.52.1/VSPAERO execution with its Python 3.13 Windows API: candidate
  wing bindings verified, original geometry hash unchanged, separate result files.
  Rectangular-wing alpha 5 degrees/Mach 0.05 returned CL 0.41136 and CD 0.017529.
  This is adapter execution evidence, not a complete-aircraft aerodynamic benchmark.
- Independent RocketPy vertical-case apogee: core 868.38 m, reference 869.12 m,
  within the predeclared 2 m case tolerance; no recovery/CP accuracy claim.
- Ten generated requirements/hardware workflow examples verify shared forward
  performance. See [tutorials](optimization-tutorials.md).
- Published Caradonna–Tung hover comparison **fails**: predicted collective 6.6125
  degrees, measured 8 degrees, predeclared tolerance 1 degree. Fixture and runner
  preserve this failure separately from passing software regressions.

## Remaining release gates

1. Independent published vehicle-level benchmarks for every family, with
   committed source inputs and predeclared accuracy tolerances. Generic
   technology/mass correlations are not substitutes for these comparisons.
2. Helicopter measured performance and forward-flight validity. Full steady rigid
   force/moment balance is implemented; the published hover comparison fails its
   tolerance. A standard annular-momentum hover model with Prandtl tip loss,
   the same untuned lift slope 5.7, profile Cd 0.012 and 20% root cutout,
   predicts about 6.93 degrees versus the measured 8 degrees (error about
   −1.07 degrees). That still misses the predeclared 1 degree gate, so the
   shipped trim model remains uniform inflow. No coefficient was fitted to the
   case. Forward flight still needs an independent comparison.
3. VTOL independent transition comparisons and installation assumptions. Planar
   force balance now exposes braking tilt and rejects exceeding its declared
   authority. Rotor-wing interference and steady moment equilibrium still need
   treatment consistent with the prescribed conceptual schedule.
4. Rocket CP/drag and recovery validation. Axial stress and fixed-free tube
   buckling are now both checked; fin flutter, parachute opening and a
   published aerodynamic comparison are not. Supplied Mach curves are mandatory
   outside the subsonic domain.
5. Broader measured propulsion validation: measured matched-drive and battery
   discharge cases, rather than coefficient interpolation and circuit identities
   alone. The lift-plus-cruise lift system retains constant electrical efficiency.
6. Installation/startup/UI and cancellation testing on a genuinely clean Windows
   machine without Python. Restricted-PATH tests on the development host are
   useful packaging evidence, but do not satisfy this independent-machine gate.

Local refinement with integer choices held fixed is implemented, and the wing
spar now uses the same cap inertia for stress and deflection. Independent
vehicle-reference tutorials remain. The current tutorials demonstrate
API/workflow equivalence using conceptual assemblies. Existing adapters and
smoke cases do not close the engineering gaps above.

## Scope boundary

Release gates apply to conceptual/preliminary design. Full transition flight
dynamics/control certification, orbital/multistage trajectories, motor internal
design and certification-level structural/dynamic substantiation remain outside
the agreed release. Such capabilities must not be added as mandatory gates by
implication. Within scope, validity limits and missing steady equilibrium or
load checks must still be explicit.

## Milestone assessment

| Milestone | Current evidence | Gate still open |
| --- | --- | --- |
| 1. Foundation | Typed API, migration, worker and frozen dependency smoke | Independent clean-Windows qualification |
| 2. Fixed-wing workflow | Both workflows, closure, measured drive, GUI, apply/export | Independent complete-aircraft benchmark |
| 3. Aircraft coverage | Four evaluators, six-component helicopter trim, endurance simulation | Rotor accuracy failure and family reference comparisons |
| 4. Rocket | Events, changing mass, domain enforcement, axial stress, tube buckling, RocketPy ascent comparison | Aerodynamic and recovery comparisons |
| 5. Workbench | Pareto/trades/robustness, recovery, local refinement, three executed adapters | Broader matched-candidate comparisons |
| 6. Release | Regression, development-host executable checks, ten workflow examples | Independent machine and vehicle-level validation |

The desktop labels the feature as a preview. A feasible flag means the candidate
satisfies implemented equations/constraints within their stated domains; it is
not an airworthiness or flight-readiness assertion. Do not call all six planned
milestones complete until these release gates are closed.

## Reproduce

```powershell
python -m unittest discover tests
python examples/optimization_studies.py fixed_wing --budget 100
python examples/optimization_studies.py rocket --budget 100
pyinstaller --noconfirm UAVDesignTool.spec
python tests/check_frozen_optimization.py dist/UAVDesignTool.exe
# Separate environment with optional packages installed:
python tests/check_optional_adapters.py
# Python 3.13 environment containing the matching OpenVSP 3.52.1 API:
python tests/check_openvsp_adapter.py path/to/OpenVSP-bin
# Independent accuracy gate: currently returns exit 1, with a saved JSON report:
python tests/check_published_rotor.py
python examples/optimization_workflows.py
```

The core build uses `requirements-windows.txt`, CPython 3.12 and Windows x64.
