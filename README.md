# UAV Design Organizer

## Aerospace optimization workbench (engineering preview)

The **Optimization** sidebar workspace adds requirements-first sizing and
fixed-hardware studies for fixed wing, multirotor, conventional helicopter,
lift-plus-cruise VTOL and suborbital rockets. It includes isolated solver workers,
Pareto/sensitivity/scenario studies, portable run snapshots and report provenance.

See the [workbench guide](docs/optimization.md),
[model methods](docs/optimization-methods.md), and
[qualification status](docs/optimization-validation.md). Model `0.4.0-preview`
adds local refinement, a consistent wing-spar check and rocket-tube buckling.
The preview is not yet the fully qualified major release: the published
helicopter hover comparison and the clean-machine gate are still open.

Use Python 3.12 and `pip install -r requirements-windows.txt` for the pinned Windows
environment. Run `python -m unittest discover tests` for regression coverage.

## AI design server (MCP)

`uav_mcp` exposes the calculators and the optimization engine as a
[Model Context Protocol](https://modelcontextprotocol.io) server, so an AI
assistant can design with the same physics instead of estimating numbers itself.
It needs no GUI and no PyQt6 at runtime. Step-by-step setup:
[docs/mcp-quickstart.md](docs/mcp-quickstart.md).

```bash
pip install "mcp>=1.10"
python -m uav_mcp                               # stdio, for Claude Code / Desktop
python -m uav_mcp --transport streamable-http   # HTTP, for remote clients
```

**Claude Code** picks up the project's `.mcp.json` automatically when opened in
this folder. To use it from anywhere:

```bash
claude mcp add --scope user uav-design -- python "C:/path/to/UAVDesignTool/uav_mcp"
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{"mcpServers": {"uav-design": {"command": "python",
  "args": ["C:/path/to/UAVDesignTool/uav_mcp"]}}}
```

| Tool | Purpose |
| --- | --- |
| `list_calculators`, `describe_calculator`, `run_calculator` | The 31 bundled calculators; inputs accept unit suffixes (`"3 lb"`); plots return as images |
| `describe_design_space`, `new_study` | Families, parameters, metrics and assumptions; editable study templates |
| `evaluate_design`, `optimize_design` | Coupled mass/power/energy closure at a point, or optimized (single objective or Pareto) |
| `sensitivity_analysis`, `uncertainty_analysis`, `sweep_design` | Design drivers (elasticities), Monte Carlo on assumptions, grid/LHS trade studies |
| `save_study`, `load_study` | Exchange studies with a project's Optimization workspace |
| `get_reference` | Methods, validation status and study format documentation |

The server also offers a `design_uav` prompt that walks through
requirements → sizing → optimization → sensitivity → subsystem checks.
`optimize_design(project_dir=...)` saves the full run where the desktop app can
open it. Extra tool folders (for example a project's `Tools/`) can be added with
`UAV_MCP_TOOL_DIRS` (path-separator list). `UAV_MCP_MAX_EVALUATIONS` (default
5000) and `UAV_MCP_MAX_SAMPLES` (default 2000) bound run time per call.

A PyQt6 desktop application for running a UAV design programme through the
Conceptual → Preliminary → Detail stage gates, plus 33 importable Python sizing
tools for fixed-wing and multirotor aircraft.

Each project is a plain folder on disk: notes are markdown files, images are
copied into `images/`, tools are Python scripts, and the whole thing is
described by a single JSON file. Nothing is locked inside a binary format.

## Running

```bash
pip install -r requirements.txt
```

```bash
python UAVDesignTool.py
```

Run the test suite:

```bash
python -m unittest discover tests
```

Build the standalone Windows executable:

```bash
pyinstaller UAVDesignTool.spec
```

## Project layout on disk

```
MyProject/
  MyProject.json           project metadata, parameters, image and tool index
  Conceptual/*.md          one markdown file per note
  Preliminary/*.md
  Detail/*.md
  images/                  every image referenced by the project
  Tools/*.py               tool scripts imported into this project
  Tools/uavlib/            shared physics library, copied in automatically
```

## Application features

- **Stage gates** — each stage has configurable required/optional parameters,
  notes, images and a design-review checkbox. A stage can only be marked
  complete once every required parameter is filled and the review is confirmed;
  only completed stages can be included in the report.
- **Autosave** — edits are written back roughly 1.5 s after you stop typing, and
  closing the window prompts if anything is still unsaved.
- **Command palette** — `Ctrl+Shift+P`, fuzzy-matched, covers navigation,
  export, theming and running any imported tool.
- **Detachable stages** — pop a stage into its own window for a second monitor.
- **Charts** — tools can return plots. They render inline, and one click
  attaches them to a stage so they flow into the Overleaf report.
- **Results feed back** — a tool's computed values can be written straight into
  a stage's parameters, where other tools can read them.
- **Overleaf export** — produces a zip of `main.tex` plus every referenced
  image, ready to upload. Text is LaTeX-escaped, and the Greek letters and
  superscripts the tools emit are translated into maths mode.
- **Light and dark themes** — `Ctrl+Shift+T`; the choice is remembered.

### Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+S` | Save project |
| `Ctrl+E` | Export to Overleaf (ZIP) |
| `Ctrl+T` | Import tool script |
| `Ctrl+Shift+P` | Command palette |
| `Ctrl+Shift+T` | Toggle light/dark theme |
| `Ctrl+Q` | Quit |
| `F1` | Shortcut reference |

## The `uavlib` physics library

Every bundled tool imports from `uavlib` rather than carrying its own copy of
the standard atmosphere or the drag polar. A copy is placed in each project's
`Tools/` folder automatically, so the scripts still run under a plain Python
interpreter after the project folder is moved elsewhere.

| Module | Contents |
| --- | --- |
| `atmosphere` | ISA to 20 km, density, Sutherland viscosity, speed of sound, density altitude, Reynolds guidance |
| `units` | Unit-aware parsing and conversion |
| `aero` | Lift-curve slope, Oswald efficiency, drag polar, skin friction, flap effectiveness, neutral point |
| `propulsion` | Momentum theory, figure of merit, propeller coefficients, electric drive chain |
| `battery` | Pack energy, C-rate, internal resistance and sag, wire gauge |
| `geometry` | Wing planform and MAC, multirotor frame layouts, motor mixing |
| `structures` | Section properties, beam bending, deflection, natural frequency |
| `report` | Consistent output formatting |
| `plotting` | matplotlib chart helpers |

All functions work in SI. Conversion happens at the edges.

## Writing a tool

A tool is an ordinary Python module with a `TOOL_METADATA` dict and a
`run(inputs)` function. It needs no imports from the application itself, so the
same file works from the GUI, from a script, or from a notebook.

```python
from uavlib import aero, report, units

TOOL_METADATA = {
    "name": "Wing Loading",
    "category": "Fixed Wing / Sizing",
    "description": "Computes wing loading from mass and wing area.",
    "inputs": [
        {"key": "mass", "label": "Total Mass", "unit": "kg", "type": "number"},
        {"key": "area", "label": "Wing Area", "unit": "m^2", "type": "number",
         "default": "0.5"},
        {"key": "surface", "label": "Finish", "type": "choice",
         "choices": ["Moulded", "Covered"], "default": "Covered"},
    ],
}

def run(inputs):
    try:
        mass = units.positive(inputs, "mass", "kg", "Mass")
        area = units.positive(inputs, "area", "m^2", "Wing area")
        loading = mass * 9.80665 / area
        r = report.Report("Wing Loading")
        r.value("Wing loading", loading, "N/m^2", 1)
        r.value("  also", units.nm2_to_ozft2(loading), "oz/ft^2", 2)
        return report.result(r, outputs={
            "Wing Loading": {"value": loading, "unit": "N/m^2"}})
    except units.UnitError as exc:
        return report.error(str(exc))
```

### Input types

| Field | Meaning |
| --- | --- |
| `key` | The dict key passed to `run()` (required) |
| `label` | Text shown in the GUI |
| `type` | `text` (default), `number`, `choice` or `file` |
| `choices` | Options for a `choice` input |
| `unit` | Shown beside the label and used as the placeholder |
| `default` | Value prefilled in the field |
| `min` / `max` | Advisory range, shown as a hint |
| `help` | Tooltip text |

Values reach `run()` as strings. `uavlib.units` parses them with an optional
unit suffix, so `10 in`, `0.254` and `10x4.7` all mean the same length; a bare
number always keeps its SI meaning.

### Return values

Return a string, or a dict for charts and structured results:

```python
{"text": "...",
 "figures": [{"title": "Drag Polar", "png": b"..."}],
 "outputs": {"Wing Area (S)": {"value": 0.31, "unit": "m^2"}},
 "warnings": ["Static margin is marginal"]}
```

`uavlib.report.result()` builds this for you. Charts render inline with an
**Attach to stage images** button; outputs get a **Save to stage parameters**
button, which is how one tool's results become another's inputs.

Tools that need instance state can instead subclass
`uav_app.tool_base.UAVTool`; both styles are supported.

Import a tool with `File ▸ Import Tool Script`. The script is copied into the
project's `Tools/` folder and re-read from disk on every run — edit the script
and just press Run again.

## Bundled tools

### `Fixed Wing Tools/`

| Tool | Purpose |
| --- | --- |
| `CGStaticMargin.py` | Neutral point, static margin and CG envelope; conventional, canard and tailless |
| `ConstraintDiagram.py` | Wing loading vs power loading; shows which requirement drives the design |
| `DragBuildup.py` | Component CD0 by wetted area, drag polar, best L/D |
| `WingSizing.py` | Wing area for cruise, with stall and Reynolds cross-checks |
| `WingGeometryCalc.py` | Span, chords, MAC and its position, sweep, tip offset for CAD |
| `VolumeCoefficientCalculator.py` | Horizontal **and vertical** tail sizing from volume coefficients |
| `SparSizing.py` | Root bending, stress, margin of safety and tip deflection |
| `SpiralParameter.py` | Spiral stability parameter, with inverse solve for dihedral |
| `DynamicStability.py` | Phugoid, short period, Dutch roll and roll subsidence |
| `ControlSurfaceEstimator.py` | Control power, roll rate, hinge moment and servo torque |
| `FlightEstimator.py` | Stall speed against load factor, flight state, manoeuvre speed |
| `RangeEnduranceEstimator.py` | Range and endurance from the polar and full efficiency chain |
| `GlidePerformance.py` | Glide ratio, minimum sink, dead-stick range |
| `TurnAndVnDiagram.py` | Turn radius and rate, V-n manoeuvre and gust envelope |
| `TakeoffLanding.py` | Ground roll, obstacle distance, hand launch and bungee |
| `ReynoldsCalc.py` | Reynolds number at altitude with low-Re guidance |
| `AirfoilConverter.py` | Selig/Lednicer/CSV coordinates → SolidWorks, DXF or CSV |
| `AirfoilPolarReader.py` | XFOIL polars: best L/D, Clmax, stall angle, operating point |

### `Multicopter Tools/`

| Tool | Purpose |
| --- | --- |
| `EnduranceEstimator.py` | Hover endurance from momentum theory, not from an assumed power |
| `ForwardFlightPower.py` | Power vs airspeed, best cruise and range speeds |
| `ThrustMotorSelection.py` | Thrust per motor for a target T/W, hover throttle, current |
| `RotorArmSizing.py` | Arm length, clearance and frame class for every layout |
| `MotorMixing.py` | Per-motor thrust for a control demand, with saturation check |
| `ArmLoads.py` | Arm bending, deflection and resonance margin |

Layouts covered: tricopter (servo yaw), quadcopter X, + and H-frame,
hexacopter, Y6, octocopter and X8 over-under. Coaxial layouts are modelled with
their shared rotor disk and ~20% interference penalty, so an X8 correctly comes
out less efficient than a quad of the same mass — and smaller than an octo.

### `Shared Tools/`

| Tool | Purpose |
| --- | --- |
| `MassProperties.py` | All-up mass, CG and inertia from a component list |
| `BatterySizing.py` | Pack energy, C-rate, sag, wire gauge, capacity trade |
| `MotorPropMatching.py` | Loaded RPM, thrust, current, tip speed, pitch match |
| `ServoTorque.py` | Hinge moment → servo torque with linkage geometry |
| `MissionEnergy.py` | Segment-by-segment energy budget with reserve |
| `CurrentBudget.py` | Propulsion, avionics and BEC loads against every limit |
| `AtmosphereCalculator.py` | Air properties, density altitude, unit conversion |

`MassToWeight.py` and `template_tool.py` sit at the repository root as a minimal
worked example and a starting template.

`airfoiltools_to_solidworks.m` is a standalone MATLAB equivalent of the aerofoil
converter and is not used by the application.

## A worked order

The tools are designed to chain, using **Save to stage parameters** to pass
results along:

1. `MassProperties` — establish all-up mass from the component list.
2. `ConstraintDiagram` — pick wing area and power together.
3. `WingGeometryCalc` — turn area and aspect ratio into real dimensions.
4. `DragBuildup` — get CD0 and the polar.
5. `CGStaticMargin` — place the CG; `VolumeCoefficientCalculator` sizes the tail.
6. `RangeEnduranceEstimator`, `GlidePerformance`, `TakeoffLanding` — check performance.
7. `SparSizing`, `ControlSurfaceEstimator`, `ServoTorque` — size the structure and controls.

For a multirotor: `MassProperties` → `RotorArmSizing` → `ThrustMotorSelection` →
`EnduranceEstimator` → `ForwardFlightPower` → `MotorMixing` → `ArmLoads`.

## Accuracy

These are conceptual and preliminary design tools. They use classical closed-form
methods — lifting-line theory, momentum theory, flat-plate skin friction,
Euler beam bending — at the fidelity appropriate to choosing between designs, not
to certifying one. Where a correlation has a limited range of validity the tool
says so. Notable limits:

- Oswald efficiency grows conservative above aspect ratio 12.
- Propeller coefficients are fitted to APC-style model props and are good to
  roughly ±20%; use measured Ct/Cp when available.
- Multirotor forward-flight power ignores rotor advance-ratio effects, so treat
  speeds above ~22 m/s as indicative.
- Dynamic stability results depend heavily on the inertia estimates.
#   U A V D e s i g n T o o l  
 
