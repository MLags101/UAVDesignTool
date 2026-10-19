"""Protocol-independent operations behind the MCP server.

Everything here returns plain JSON-safe dicts so it can be unit tested without
the ``mcp`` package. Heavy results (full solver histories, every sweep row) are
summarised: an assistant needs the decision-relevant numbers, not megabytes of
evaluation journal. Full snapshots can still be written to a project folder.
"""

import contextlib
import glob
import json
import math
import os
import sys
import threading
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLBACKEND", "Agg")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uav_app.tool_base import ToolError, ToolManager, normalise_result  # noqa: E402
from uavlib.optimization import (  # noqa: E402
    StudyDefinition, evaluate, optimize, sweep, assess_uncertainty, sensitivity, template,
)
from uavlib.optimization.schema import MODEL_VERSION  # noqa: E402
from uavlib.optimization.storage import StudyStore  # noqa: E402
from uavlib.optimization.templates import FAMILY_PARAMETERS, METRICS, PARAMETERS  # noqa: E402

TOOL_DIRS = ["Fixed Wing Tools", "Multicopter Tools", "Shared Tools"]
FAMILIES = tuple(FAMILY_PARAMETERS)
SEGMENT_KINDS = ("cruise", "hover", "climb", "descent", "transition", "manual")
SOLVERS = ("differential_evolution", "slsqp")
COMPONENT_KINDS = {
    "motor": "max_power (shaft W); quantity counts installed motors",
    "controller": "max_current (A per controller)",
    "battery": "energy (J), voltage (V), resistance (ohm), min_voltage (V), max_current (A); one aggregate pack",
    "propeller": "diameter (m); winged flight also needs efficiency_map and max_power_map ([[airspeed, value], ...])",
    "engine": "max_power (W), fuel_flow_map ([[shaft W, kg/s], ...])",
    "tank": "fuel_mass (kg per tank); component mass is the empty tank",
    "main_rotor": "diameter (m), chord (m), blades (integer), rpm",
    "lift_rotor": "diameter (m), chord (m), blades (integer), rpm",
    "tail_rotor": "diameter (m)",
    "transmission": "max_power (W)",
    "lift_motor": "max_power (W per motor)",
    "wing": "area (m^2), aspect_ratio, spar_cap_area (m^2 per cap), spar_depth (m)",
    "frame": "arm_length, arm_diameter, arm_wall (m)",
    "rocket_motor": "thrust_curve ([[s, N], ...]), propellant_curve ([[s, kg remaining], ...])",
    "aerodynamics": "rocket only: cd_mach ([[Mach, CD], ...]), cp_mach ([[Mach, CP from nose m], ...])",
}
REFERENCES = {
    "workbench": ("docs/optimization.md", "How studies, workflows, hardware records and trade studies work"),
    "methods": ("docs/optimization-methods.md", "Physics models, equations and their stated limits"),
    "validation": ("docs/optimization-validation.md", "Qualification status and what has not been validated"),
    "tutorials": ("docs/optimization-tutorials.md", "Worked study examples"),
    "library": ("README.md", "Application overview and the uavlib physics library"),
}

MAX_EVALUATIONS = int(os.environ.get("UAV_MCP_MAX_EVALUATIONS", "5000"))
MAX_SAMPLES = int(os.environ.get("UAV_MCP_MAX_SAMPLES", "2000"))

# matplotlib's pyplot state and the tool modules are not thread safe.
_calculator_lock = threading.Lock()
_registry: dict[str, dict[str, Any]] | None = None


# --------------------------------------------------------------------- helpers
def clean(value: Any) -> Any:
    """Make a value JSON safe: non-finite floats become strings, bytes are dropped."""
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if hasattr(value, "item"):  # numpy scalar
        return clean(value.item())
    return str(value)


def parse_study(study: dict | str) -> StudyDefinition:
    if isinstance(study, str):
        try:
            study = json.loads(study)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Study is not valid JSON: {exc}") from exc
    if not isinstance(study, dict):
        raise ValueError("Study must be a JSON object as returned by new_study")
    try:
        definition = StudyDefinition.from_dict(study)
    except TypeError as exc:
        raise ValueError(f"Study has an unexpected field: {exc}") from exc
    definition.validate()
    return definition


def _limit_budget(definition: StudyDefinition, warnings: list[str]):
    if definition.max_evaluations > MAX_EVALUATIONS:
        warnings.append(f"max_evaluations reduced from {definition.max_evaluations} to the server "
                        f"limit {MAX_EVALUATIONS} (set UAV_MCP_MAX_EVALUATIONS to change it).")
        definition.max_evaluations = MAX_EVALUATIONS


def compact_evaluation(result, include_history=False) -> dict[str, Any]:
    data = result.to_dict() if hasattr(result, "to_dict") else dict(result)
    data["design"] = {k: v for k, v in data.get("design", {}).items() if not k.startswith("_")}
    if not include_history:
        data.pop("mission_history", None)
        data.pop("endurance_history", None)
    if not data.get("sampled_inputs"):
        data.pop("sampled_inputs", None)
    if not data.get("limiting_scenarios"):
        data.pop("limiting_scenarios", None)
    return clean(data)


def _objective_labels(definition):
    return [f"{o.sense} {o.metric} [{METRICS.get(o.metric, '')}]".rstrip(" []")
            for o in definition.objectives]


# ----------------------------------------------------------------- calculators
def _discover() -> dict[str, dict[str, Any]]:
    global _registry
    if _registry is not None:
        return _registry
    folders = [ROOT / name for name in TOOL_DIRS]
    folders += [Path(p) for p in os.environ.get("UAV_MCP_TOOL_DIRS", "").split(os.pathsep) if p]
    registry = {}
    for folder in folders:
        for path in sorted(glob.glob(str(folder / "*.py"))):
            identifier = Path(path).stem
            if identifier.startswith("_") or identifier in registry:
                continue
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    tool, metadata = ToolManager.load_tool_from_file(path)
            except ToolError as exc:
                print(f"uav-mcp: skipped {path}: {exc}", file=sys.stderr)
                continue
            if not metadata["category"]:
                metadata["category"] = folder.name
            registry[identifier] = {"tool": tool, "metadata": metadata, "path": path}
    _registry = registry
    return registry


def _calculator(name: str) -> tuple[str, dict[str, Any]]:
    registry = _discover()
    if name in registry:
        return name, registry[name]
    wanted = name.strip().lower()
    for identifier, entry in registry.items():
        if wanted in (identifier.lower(), entry["metadata"]["name"].lower()):
            return identifier, entry
    raise ValueError(f"Unknown calculator '{name}'. Call list_calculators for valid ids.")


def list_calculators(category: str = "") -> dict[str, Any]:
    rows = []
    for identifier, entry in _discover().items():
        meta = entry["metadata"]
        if category and category.lower() not in meta["category"].lower():
            continue
        rows.append({"id": identifier, "name": meta["name"], "category": meta["category"],
                     "description": meta["description"]})
    rows.sort(key=lambda r: (r["category"], r["id"]))
    return {"count": len(rows), "calculators": rows}


def describe_calculator(calculator: str) -> dict[str, Any]:
    identifier, entry = _calculator(calculator)
    meta = entry["metadata"]
    inputs = []
    for spec in meta["inputs"]:
        row = {k: v for k, v in spec.items() if v not in ("", None, [])}
        row["required"] = not spec["default"] and spec["type"] != "choice"
        inputs.append(row)
    return {"id": identifier, "name": meta["name"], "category": meta["category"],
            "description": meta["description"], "inputs": inputs,
            "input_format": ("Pass values as numbers or strings. Bare numbers use the listed SI "
                             "unit; strings may carry a unit suffix, e.g. '3.3 lb', '10 in', "
                             "'45 km/h', '5000 mAh'. Omitted inputs use their defaults.")}


def run_calculator(calculator: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a calculator. Figures are returned as raw PNG bytes under ``figures``."""
    identifier, entry = _calculator(calculator)
    meta = entry["metadata"]
    known = {spec["key"]: spec for spec in meta["inputs"]}
    inputs = dict(inputs or {})
    unknown = sorted(set(inputs) - set(known))
    if unknown:
        raise ValueError(f"Unknown inputs for {identifier}: {', '.join(unknown)}. "
                         f"Valid keys: {', '.join(known)}")
    values = {}
    for key, spec in known.items():
        value = inputs.get(key)
        if value is None or value == "":
            value = spec["default"] or (spec["choices"][0] if spec["type"] == "choice" else "")
        values[key] = ("Yes" if value else "No") if isinstance(value, bool) else str(value)
    with _calculator_lock, contextlib.redirect_stdout(sys.stderr):
        try:
            raw = entry["tool"].run(values)
        except Exception as exc:  # a tool bug must not take the server down
            raise ValueError(f"{identifier} failed: {exc}") from exc
    result = normalise_result(raw)
    text = result["text"]
    error = text[len("Error:"):].strip() if text.startswith("Error:") else ""
    return {"id": identifier, "name": meta["name"], "ok": not error,
            "error": error or None, "inputs_used": values,
            "outputs": clean(result["outputs"]), "warnings": result["warnings"],
            "report": text, "figures": result["figures"]}


# ------------------------------------------------------------- design studies
def describe_design_space(family: str = "") -> dict[str, Any]:
    families = [family] if family else list(FAMILIES)
    for name in families:
        if name not in FAMILIES:
            raise ValueError(f"Unknown family '{name}'. Choose from {', '.join(FAMILIES)}")
    out = {"model_version": MODEL_VERSION, "families": {}, "metrics": METRICS,
           "parameters": {k: v[0] for k, v in PARAMETERS.items()},
           "mission_segment_kinds": SEGMENT_KINDS, "solvers": SOLVERS,
           "requirement_senses": [">=", "<=", "=="], "objective_senses": ["min", "max"],
           "workflows": {"requirements": "Size the vehicle (mass, power, energy closed) to meet the "
                                          "mission. Installed power/energy are outputs.",
                         "hardware": "Analyse/optimise around supplied components; their "
                                     "ratings are locked."},
           "hardware_component_kinds": COMPONENT_KINDS}
    for name in families:
        study = template(name)
        baseline = evaluate(study)
        out["families"][name] = {
            "design_parameters": {k: PARAMETERS[k][0] for k in FAMILY_PARAMETERS[name]},
            "default_free_variables": [v.key for v in study.variables],
            "assumption_defaults": study.vehicle.assumptions,
            "available_metrics": sorted(baseline.metrics) if baseline.valid else [],
        }
    return clean(out)


def new_study(family: str = "fixed_wing", workflow: str = "requirements",
              propulsion: str = "electric", name: str = "") -> dict[str, Any]:
    if workflow not in ("requirements", "hardware"):
        raise ValueError("workflow must be 'requirements' or 'hardware'")
    if propulsion not in ("electric", "fuel"):
        raise ValueError("propulsion must be 'electric' or 'fuel'")
    study = template(family, workflow, propulsion)
    if name:
        study.name = name
    return clean(study.to_dict())


def evaluate_design(study, design: dict[str, float] | None = None,
                    include_history: bool = False) -> dict[str, Any]:
    definition = parse_study(study)
    result = evaluate(definition, design or {})
    return {"model_version": MODEL_VERSION, "objectives": _objective_labels(definition),
            "result": compact_evaluation(result, include_history)}


def optimize_design(study, max_candidates: int = 10, project_dir: str = "") -> dict[str, Any]:
    definition = parse_study(study)
    warnings: list[str] = []
    _limit_budget(definition, warnings)
    result = optimize(definition)
    candidates = sorted(result.candidates, key=lambda r: tuple(r.objectives))
    history = result.history
    feasible_rows = [row for row in history if row["feasible"]]
    trace = []
    if len(definition.objectives) == 1:
        best = math.inf
        for row in history:
            if row["feasible"] and row["objectives"][0] < best:
                best = row["objectives"][0]
                trace.append({"evaluation": row["evaluation"], "objective": best})
    out = {"status": result.status, "solver_message": result.solver_message,
           "evaluations": result.evaluations, "feasible_evaluations": len(feasible_rows),
           "objectives": _objective_labels(definition),
           "note": "Objective values are scaled and sign-flipped for 'max'; read metrics for physical values.",
           "baseline": compact_evaluation(result.baseline),
           "candidate_count": len(candidates),
           "candidates": [compact_evaluation(r) for r in candidates[:max(1, max_candidates)]],
           "improvement_trace": trace[-15:], "provenance": result.provenance,
           "input_hash": result.input_hash, "model_version": result.model_version,
           "warnings": warnings}
    if project_dir:
        store = StudyStore(project_dir)
        out["saved_study"] = store.save_study(definition)
        out["saved_run"] = store.save_run(definition, result)
    return clean(out)


def sweep_design(study, specification: dict[str, Any], max_rows: int = 20) -> dict[str, Any]:
    definition = parse_study(study)
    spec = dict(specification or {})
    if spec.get("kind", "latin_hypercube") == "latin_hypercube" and int(spec.get("samples", 25)) > MAX_SAMPLES:
        raise ValueError(f"samples exceeds the server limit {MAX_SAMPLES} (UAV_MCP_MAX_SAMPLES)")
    if spec.get("kind") == "grid":
        total = math.prod(len(v) for v in spec.get("axes", {}).values())
        if total > MAX_SAMPLES:
            raise ValueError(f"Grid has {total} points; the server limit is {MAX_SAMPLES}")
    result = sweep(definition, spec)
    rows = result.evaluations
    ranked = sorted(rows, key=lambda r: (not r.feasible, not r.valid,
                                         tuple(r.objectives) if r.objectives else (math.inf,)))
    feasible = [r for r in rows if r.feasible]
    ranges = {}
    for v in definition.variables:
        values = [r.design[v.key] for r in feasible if v.key in r.design]
        if values:
            ranges[v.key] = [min(values), max(values)]
    errors = sorted({e for r in rows for e in r.errors})
    return clean({"kind": result.kind, "status": result.status, "samples": len(rows),
                  "feasible": len(feasible), "invalid": sum(not r.valid for r in rows),
                  "objectives": _objective_labels(definition),
                  "feasible_variable_ranges": ranges, "distinct_errors": errors[:10],
                  "best_rows": [compact_evaluation(r) for r in ranked[:max(1, max_rows)]]})


def sensitivity_analysis(study, design: dict[str, float] | None = None, fraction: float = 0.01,
                         metrics: list[str] | None = None) -> dict[str, Any]:
    definition = parse_study(study)
    design = dict(design or {})
    nominal = evaluate(definition, design)
    if not nominal.valid:
        raise ValueError("Sensitivity needs a valid nominal design: " + "; ".join(nominal.errors))
    result = sensitivity(definition, design, fraction)
    wanted = set(metrics or nominal.metrics)
    derivatives, elasticities = {}, {}
    for key, row in result.summary.items():
        x = design.get(key, next(v.initial for v in definition.variables if v.key == key))
        derivatives[key] = {m: d for m, d in row.items() if m in wanted}
        # Elasticity: percent change in metric per percent change in variable.
        elasticities[key] = {m: d * x / nominal.metrics[m] for m, d in row.items()
                             if m in wanted and nominal.metrics.get(m)}
    return clean({"status": result.status, "step_fraction_of_range": fraction,
                  "nominal_metrics": {m: v for m, v in nominal.metrics.items() if m in wanted},
                  "derivatives": derivatives, "elasticities": elasticities})


def uncertainty_analysis(study, specification: dict[str, Any],
                         design: dict[str, float] | None = None) -> dict[str, Any]:
    definition = parse_study(study)
    spec = dict(specification or {})
    if int(spec.get("samples", 100)) > MAX_SAMPLES:
        raise ValueError(f"samples exceeds the server limit {MAX_SAMPLES} (UAV_MCP_MAX_SAMPLES)")
    result = assess_uncertainty(definition, design or {}, spec)
    summary = dict(result.summary)
    summary["percentiles"] = {m: {"p5": p[0], "p50": p[1], "p95": p[2]}
                              for m, p in summary.get("percentiles", {}).items()}
    errors = sorted({e for r in result.evaluations for e in r.errors})
    return clean({"status": result.status, "summary": summary, "distinct_errors": errors[:10],
                  "note": "Sampled feasibility describes the stated assumption ranges; it is not "
                          "a certified probability."})


def save_study(study, project_dir: str) -> dict[str, Any]:
    definition = parse_study(study)
    relative = StudyStore(project_dir).save_study(definition)
    return {"project_dir": str(Path(project_dir).resolve()), "saved_study": relative}


def load_study(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "study" in data and isinstance(data["study"], dict):  # worker request files
        data = data["study"]
    return clean(parse_study(data).to_dict())


def get_reference(topic: str) -> str:
    if topic not in REFERENCES:
        raise ValueError(f"Unknown topic '{topic}'. Choose from {', '.join(REFERENCES)}")
    return (ROOT / REFERENCES[topic][0]).read_text(encoding="utf-8")
