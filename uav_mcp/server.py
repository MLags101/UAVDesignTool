"""MCP server: UAV engineering calculators and the conceptual design optimizer.

Run over stdio (what Claude Code / Claude Desktop launch)::

    python -m uav_mcp

or as a streamable HTTP endpoint for remote clients::

    python -m uav_mcp --transport streamable-http
"""

import argparse
import functools
from typing import Any

import anyio.to_thread

try:  # mcp >= 2
    from mcp.server.mcpserver import Image, MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer, Image
    from mcp.server.fastmcp.exceptions import ToolError

from . import service

INSTRUCTIONS = f"""\
UAV conceptual and preliminary design toolkit (physics model {service.MODEL_VERSION}).
All numbers come from deterministic engineering models: standard atmosphere,
drag polars, momentum/blade-element rotor theory, electric drive and battery
sag models, beam structures and coupled mass/power/energy closure. Prefer these
tools to mental arithmetic, and quote their numbers, units and warnings.

Two layers:
1. Calculators (list_calculators -> describe_calculator -> run_calculator):
   31 single-discipline tools for fixed wing, multirotor and shared subsystems
   (wing sizing, constraint diagram, drag build-up, static margin, dynamic
   stability, V-n, takeoff, spar sizing, thrust/motor selection, battery sizing,
   motor-prop matching, current budget, mission energy...). Inputs accept unit
   suffixes such as '3 lb', '10 in', '5000 mAh'.
2. Coupled design studies for fixed_wing, multirotor, helicopter, lift_cruise
   (VTOL) and rocket: describe_design_space -> new_study -> edit the JSON ->
   evaluate_design -> optimize_design -> sensitivity_analysis /
   uncertainty_analysis / sweep_design. Studies are SI throughout.

Good practice: start from the mission requirements; size with the constraint
diagram or a requirements study before choosing parts; check every margin,
warning and limiting scenario; run sensitivity on the result to see which
assumptions drive it; run uncertainty on technology assumptions (cd0,
specific_energy, efficiencies) before trusting a tight margin. Templates are
technology assumptions, not measured hardware. The optimizer is an engineering
preview -- read get_reference('validation') before presenting results as final.
"""

mcp = MCPServer("uav-design", instructions=INSTRUCTIONS)


async def _offload(fn, *args, **kwargs):
    """Run blocking physics off the event loop so the server stays responsive.

    Input and model errors become ToolError so the client sees the actual
    message (which names the bad field) instead of a generic failure.
    """
    try:
        return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))
    except (ValueError, KeyError, TypeError, OSError, ImportError) as exc:
        raise ToolError(f"{type(exc).__name__}: {exc}") from exc


# ----------------------------------------------------------------- calculators
@mcp.tool(structured_output=False)
async def list_calculators(category: str = "") -> dict[str, Any]:
    """List the engineering calculators. Optionally filter by category text,
    e.g. 'Fixed Wing', 'Multirotor', 'Shared', 'Stability', 'Propulsion'."""
    return await _offload(service.list_calculators, category)


@mcp.tool(structured_output=False)
async def describe_calculator(calculator: str) -> dict[str, Any]:
    """Show a calculator's inputs: keys, SI units, defaults, choices, guidance
    and which are required. Call this before run_calculator."""
    return await _offload(service.describe_calculator, calculator)


@mcp.tool(structured_output=False)
async def run_calculator(calculator: str, inputs: dict[str, Any] | None = None,
                         include_figures: bool = False) -> list[Any]:
    """Run a calculator by id (from list_calculators).

    inputs maps input keys to numbers or unit-suffixed strings ('2.2 lb').
    Returns structured outputs (value + unit), warnings and the full text
    report. Set include_figures to also receive any plots (constraint diagram,
    drag polar, V-n diagram...) as PNG images."""
    result = await _offload(service.run_calculator, calculator, inputs)
    figures = result.pop("figures")
    result["figure_titles"] = [f["title"] for f in figures]
    content: list[Any] = [result]
    if include_figures:
        content += [Image(data=f["png"], format="png") for f in figures]
    return content


# ------------------------------------------------------------- design studies
@mcp.tool(structured_output=False)
async def describe_design_space(family: str = "") -> dict[str, Any]:
    """Reference for coupled studies: vehicle families, their design parameters
    and units, technology assumption defaults, available metrics, mission
    segment kinds, solvers and hardware component kinds. Pass a family
    (fixed_wing, multirotor, helicopter, lift_cruise, rocket) to narrow it."""
    return await _offload(service.describe_design_space, family)


@mcp.tool(structured_output=False)
async def new_study(family: str = "fixed_wing", workflow: str = "requirements",
                    propulsion: str = "electric", name: str = "") -> dict[str, Any]:
    """Create a study template to edit. workflow 'requirements' sizes a vehicle
    to a mission (installed power and energy are outputs); 'hardware' analyses
    supplied components. propulsion is 'electric' or 'fuel'.

    The returned JSON has vehicle.parameters (geometry, payload, speed),
    vehicle.assumptions (technology: cd0, specific_energy, efficiencies...),
    mission.segments, variables (bounds of free design variables),
    requirements ({metric, limit, sense}), objectives ({metric, sense}),
    scenarios, solver, seed and max_evaluations. Edit it and pass the whole
    object to the analysis tools."""
    return await _offload(service.new_study, family, workflow, propulsion, name)


@mcp.tool(structured_output=False)
async def evaluate_design(study: dict[str, Any], design: dict[str, float] | None = None,
                          include_history: bool = False) -> dict[str, Any]:
    """Analyse one design point without optimizing. design overrides free
    variable values (defaults to their initial values). Returns metrics, mass
    breakdown, requirement margins (>= 0 means satisfied), feasibility,
    convergence and warnings. include_history adds per-segment mission data."""
    return await _offload(service.evaluate_design, study, design, include_history)


@mcp.tool(structured_output=False)
async def optimize_design(study: dict[str, Any], max_candidates: int = 10,
                          project_dir: str = "") -> dict[str, Any]:
    """Optimize the study's free variables for its objectives subject to its
    requirements. One objective uses differential evolution (or SLSQP); two or
    three objectives return a Pareto front via NSGA-II. Runtime scales with
    max_evaluations (about 25 ms each). If project_dir is a UAV Design
    Organizer project folder, the study and full run are saved there so they
    open in the desktop app's Optimization workspace."""
    return await _offload(service.optimize_design, study, max_candidates, project_dir)


@mcp.tool(structured_output=False)
async def sweep_design(study: dict[str, Any], specification: dict[str, Any],
                       max_rows: int = 20) -> dict[str, Any]:
    """Trade study over the free variables. specification is either
    {"kind": "grid", "axes": {"wing_area": [0.5, 0.7, 0.9], "aspect_ratio": [6, 8, 10]}}
    or {"kind": "latin_hypercube", "samples": 40, "seed": 42}.
    Returns feasibility counts, feasible variable ranges and the best rows."""
    return await _offload(service.sweep_design, study, specification, max_rows)


@mcp.tool(structured_output=False)
async def sensitivity_analysis(study: dict[str, Any], design: dict[str, float] | None = None,
                               fraction: float = 0.01,
                               metrics: list[str] | None = None) -> dict[str, Any]:
    """Finite-difference sensitivity of every metric to each continuous free
    variable at a design point. Returns derivatives and elasticities (% change
    in metric per % change in variable) -- use these to find the design drivers.
    metrics optionally limits the output, e.g. ["takeoff_mass", "endurance"]."""
    return await _offload(service.sensitivity_analysis, study, design, fraction, metrics)


@mcp.tool(structured_output=False)
async def uncertainty_analysis(study: dict[str, Any], specification: dict[str, Any],
                               design: dict[str, float] | None = None) -> dict[str, Any]:
    """Monte Carlo over technology assumptions with the sized hardware held fixed.
    specification: {"samples": 200, "seed": 42, "inputs": {"cd0": {"distribution":
    "uniform", "lower": 0.03, "upper": 0.045}, "specific_energy": {"distribution":
    "normal", "mean": 700000, "std": 30000}}}. Returns sampled feasibility and
    p5/p50/p95 of every metric."""
    return await _offload(service.uncertainty_analysis, study, specification, design)


@mcp.tool(structured_output=False)
async def save_study(study: dict[str, Any], project_dir: str) -> dict[str, Any]:
    """Save a study into a UAV Design Organizer project folder
    (Optimization/studies/) so it can be opened and run in the desktop app."""
    return await _offload(service.save_study, study, project_dir)


@mcp.tool(structured_output=False)
async def load_study(path: str) -> dict[str, Any]:
    """Load a study JSON file (saved by the desktop app or save_study)."""
    return await _offload(service.load_study, path)


@mcp.tool(structured_output=False)
async def get_reference(topic: str) -> str:
    """Read design documentation. topic: 'methods' (equations and model limits),
    'validation' (what is and is not qualified), 'workbench' (study format,
    hardware records, trade studies), 'tutorials', or 'library' (overview)."""
    return await _offload(service.get_reference, topic)


# ------------------------------------------------------- resources and prompts
for _topic, (_path, _summary) in service.REFERENCES.items():
    mcp.resource(f"uav://docs/{_topic}", name=f"{_topic}", description=_summary,
                 mime_type="text/markdown")(functools.partial(service.get_reference, _topic))


@mcp.prompt()
def design_uav(mission: str, vehicle_type: str = "") -> str:
    """Run a requirements-first UAV design using the engineering tools."""
    hint = f" The intended configuration is {vehicle_type}." if vehicle_type else ""
    return f"""Design a UAV for this mission: {mission}.{hint}

Work like a conceptual design engineer and use the uav-design tools for every number:
1. Turn the mission into quantified requirements (payload, endurance or range,
   cruise speed, altitude, stall/landing speed, climb, reserve). State assumptions.
2. Pick the configuration (fixed_wing, multirotor, helicopter, lift_cruise) and justify it.
3. Run the relevant calculators for first-order sizing (e.g. ConstraintDiagram,
   WingSizing, ThrustMotorSelection, BatterySizing, AtmosphereCalculator).
4. Build a requirements study with new_study, encode the mission segments and
   requirements, evaluate the baseline, then optimize_design.
5. Check margins, warnings and convergence. Run sensitivity_analysis to find the
   design drivers and uncertainty_analysis on the key technology assumptions.
6. Verify subsystems on the chosen design with calculators (static margin, spar
   sizing, V-n, motor-prop matching, current budget).
7. Summarise the design in a table with units, the binding constraints, risks,
   and which results come from preview-status models (see get_reference('validation'))."""


def main(argv=None):
    parser = argparse.ArgumentParser(description="UAV design MCP server")
    parser.add_argument("--transport", choices=("stdio", "streamable-http", "sse"), default="stdio")
    args = parser.parse_args(argv)
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
