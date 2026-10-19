# Reproducible workflow tutorials

Run from the repository root using the pinned core environment:

```powershell
python examples/optimization_workflows.py
```

This produces `build/workflow-tutorials/<family>/<workflow>/study.json` and
`evaluation.json` for all five families and both workflows. Each pair uses the
same forward model and verifies equal mass and mission energy (rocket: apogee).
These are synthetic conceptual demonstrations, not validated manufacturer builds.

Load a definition through the Python API:

```python
import json
from pathlib import Path
from uavlib.optimization import StudyDefinition, DesignVariable, evaluate, optimize

path = Path("build/workflow-tutorials/fixed_wing/hardware/study.json")
study = StudyDefinition.from_dict(json.loads(path.read_text()))
baseline = evaluate(study)
assert baseline.valid, baseline.errors
# The generated hardware example initially has no free variables: analysis only.
study.variables = [DesignVariable("wing_area", .7, .5, 1., scale=.7)]
study.max_evaluations = 100
result = optimize(study)
print(result.status, len(result.candidates))
```

Omitting `unit` uses the canonical SI unit advertised by the registered model.
Hardware-owned dimensions cannot be made free. Component placement can
use `component.<id>.position` without modifying component identity or ratings.

| Family | Requirements example | Hardware example and interpretation |
| --- | --- | --- |
| `fixed_wing` | Wing/structure, propulsion and battery close around the cruise mission | Motor, propeller and pack fixed; investigate free wing area or cruise speed |
| `multirotor` | Rotor disk/frame and hover energy coupled to takeoff mass | Fixed rotors and power/storage; inspect thrust reserve, current and arm loads |
| `helicopter` | Main/tail rotor, transmission and mission power | Fixed rotor/drivetrain; inspect tail thrust, transmission power and all trim residuals; published accuracy gate remains open |
| `lift_cruise` | Hover, prescribed transitions and cruise with separate lift/cruise power | Fixed lift installation and cruise drive; inspect transition forces and energy, and carried lift-system mass |
| `rocket` | Declared conceptual propulsion template and point-mass flight | Exact supplied motor thrust/remaining-mass curves; inspect guide exit, CG history, Mach domain and recovery |

For the requirements-first example, review mission, assumptions and bounds before
running `optimize`. For the hardware example, replace synthetic component records
with measured parts and cite their sources before interpreting results as hardware
predictions. Coefficient maps must span the operating domain; static thrust alone
does not establish cruise capability. See [hardware formats](optimization.md).

In the desktop, follow Vehicle → Requirements and mission → Hardware and
assumptions → Variables and objectives → Run → Compare results. Run a baseline,
then inspect validity, numerical convergence and constraint feasibility separately.
Select Mission energy or Endurance mission to distinguish the prescribed flight
from the endurance extension. Pareto studies have selectable objective axes and
do not automatically choose a design. Save plot stores a PNG alongside the run.

Only Apply selected design changes project parameters, after a change preview.
Saving/exporting a study or running a comparison does not apply it. Old runs become
stale when inputs change. All examples remain subject to the explicit
[qualification gaps](optimization-validation.md).
