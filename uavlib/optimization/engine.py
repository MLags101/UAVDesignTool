"""Solver-independent study evaluation and reproducible optimization drivers."""
from copy import deepcopy
from dataclasses import replace
import itertools
import math
import platform
from .schema import EvaluationResult, OptimizationResult, StudyResult
from .vehicles import REGISTRY
from . import rocket  # register the built-in trajectory model


def _parameters(study, design):
    p = dict(study.vehicle.parameters)
    variables = {v.key: v for v in study.variables}
    unknown = set(design) - set(variables)
    if unknown:
        raise ValueError("Unknown design variables: " + ", ".join(sorted(unknown)))
    model = REGISTRY[study.vehicle.family]
    if set(p) - set(model.parameters):
        raise ValueError("Unknown vehicle parameters: " + ", ".join(sorted(set(p) - set(model.parameters))))
    locked = set()
    hardware_bindings = {
        "propeller": {"rotor_diameter"},
        "main_rotor": {"rotor_diameter", "rotor_rpm", "blade_chord", "blade_count"},
        "lift_rotor": {"rotor_diameter", "rotor_rpm", "blade_chord", "blade_count"},
        "tail_rotor": {"tail_rotor_diameter"},
        "battery": {"energy_capacity"}, "tank": {"fuel_mass"},
        "motor": {"installed_power"}, "engine": {"installed_power"},
        "rocket_motor": {"propellant_mass", "burn_time"},
        "wing": {"wing_area", "aspect_ratio"},
        "frame": {"arm_length", "arm_diameter", "arm_wall"},
    }
    if study.workflow == "hardware":
        for c in study.vehicle.components:
            locked |= hardware_bindings.get(c.kind, set())
    positions = {f"component.{c.id}.position" for c in study.vehicle.components}
    for key, v in variables.items():
        if key not in model.parameters and key not in positions:
            raise ValueError(f"Unknown variable {key}")
        expected_unit = "m" if key in positions else model.parameters[key][0]
        if v.unit not in ("", expected_unit):
            raise ValueError(f"Variable {key} uses canonical unit {expected_unit or 'dimensionless'}, not {v.unit}")
        if study.workflow == "requirements" and key in ("installed_power", "energy_capacity", "fuel_mass"):
            raise ValueError(f"{key} is derived by sizing; change the mission or technology assumptions instead")
        if key in locked:
            raise ValueError(f"Hardware locks {key}; remove it from free variables")
        value = design.get(key, v.initial)
        if not math.isfinite(value) or not v.lower <= value <= v.upper:
            raise ValueError(f"{key} is outside finite bounds")
        if not v.free and value != v.initial:
            raise ValueError(f"Cannot change fixed variable {key}")
        if v.integer and value != int(value):
            raise ValueError(f"{key} must be an integer")
        p[key] = value
    return p


def _evaluate_one(study, design, sized=None):
    model = REGISTRY.get(study.vehicle.family)
    if model is None:
        raise ValueError(f"Unsupported vehicle family: {study.vehicle.family}")
    p = _parameters(study, design)
    if sized and study.workflow == "requirements" and study.vehicle.family != "rocket":
        p.update(_fixed_power=sized.metrics["cruise_installed_power"], _fixed_lift_power=sized.metrics["installed_lift_power"], _fixed_energy=sized.metrics["energy_capacity"],
                 _fixed_fuel=sized.metrics["fuel_capacity"])
        if "_sized_cap_area" in sized.design:
            p.update(_fixed_cap_area=sized.design["_sized_cap_area"], _fixed_airframe_mass=sized.design["_sized_airframe_mass"])
    for entry in study.requirements + study.objectives:
        if entry.metric not in model.metrics:
            raise ValueError(f"Unknown metric: {entry.metric}")
    result = model.evaluate(study, p)
    if not result.valid:
        return result
    for i, req in enumerate(study.requirements):
        if req.segment:
            rows = [row for row in result.mission_history if row.get("segment") == req.segment]
            field = {"peak_power": "power", "peak_current": "current", "min_voltage": "voltage",
                     "takeoff_mass": "mass", "energy_required": "energy", "max_acceleration": "acceleration",
                     "max_dynamic_pressure": "dynamic_pressure", "max_mach": "mach"}.get(req.metric, req.metric)
            if not rows or any(field not in row for row in rows):
                raise ValueError(f"Metric {req.metric} unavailable in segment {req.segment}")
            values = [row[field] for row in rows]
        else:
            if req.metric not in result.metrics:
                raise ValueError(f"Metric {req.metric} unavailable for this family")
            values = [result.metrics[req.metric]]
        raw = [(x - req.limit if req.sense == ">=" else req.limit - x if req.sense == "<="
                else -abs(x - req.limit)) for x in values]
        result.margins[f"requirement.{i}.{req.metric}"] = (min(raw) + req.tolerance) / req.scale
    result.objectives = []
    for objective in study.objectives:
        if objective.metric not in result.metrics:
            raise ValueError(f"Objective {objective.metric} unavailable for this family")
        result.objectives.append(result.metrics[objective.metric] / objective.scale * (1 if objective.sense == "min" else -1))
    if any(not math.isfinite(v) for v in list(result.metrics.values()) + list(result.margins.values()) + result.objectives):
        raise ValueError("Model produced nonfinite output")
    result.feasible = result.converged and all(m >= -1e-8 for m in result.margins.values())
    return result


def evaluate(study, design=None):
    """Evaluate without changing the input study or its component records."""
    return _evaluate(study, design)


def _evaluate(study, design=None, sized=None):
    design = dict(design or {})
    try:
        study.validate()
        result = _evaluate_one(study, design, sized)
        if study.robust and result.valid:
            result.limiting_scenarios = {k: "Nominal" for k in result.margins}
            for scenario in study.scenarios:
                alternate = deepcopy(study)
                alternate.robust = False
                alternate.vehicle.parameters["payload"] += scenario.payload_delta
                for variable in alternate.variables:
                    if variable.key == "payload":
                        variable.initial += scenario.payload_delta
                        variable.lower += scenario.payload_delta
                        variable.upper += scenario.payload_delta
                adjusted = dict(design)
                if study.vehicle.family == "rocket":
                    alternate.vehicle.parameters["launch_altitude"] = alternate.vehicle.parameters.get("launch_altitude", 0.) + scenario.altitude_offset
                    for variable in alternate.variables:
                        if variable.key == "launch_altitude":
                            variable.initial += scenario.altitude_offset
                            variable.lower += scenario.altitude_offset
                            variable.upper += scenario.altitude_offset
                    if "launch_altitude" in adjusted:
                        adjusted["launch_altitude"] += scenario.altitude_offset
                if "payload" in adjusted:
                    adjusted["payload"] += scenario.payload_delta
                for segment in alternate.mission.segments:
                    segment.altitude += scenario.altitude_offset
                    if segment.end_altitude is not None:
                        segment.end_altitude += scenario.altitude_offset
                    segment.speed *= scenario.speed_factor
                    if segment.end_speed is not None:
                        segment.end_speed *= scenario.speed_factor
                alternate.vehicle.parameters["cruise_speed"] *= scenario.speed_factor
                for variable in alternate.variables:
                    if variable.key == "cruise_speed":
                        variable.initial *= scenario.speed_factor
                        variable.lower *= scenario.speed_factor
                        variable.upper *= scenario.speed_factor
                if "cruise_speed" in adjusted:
                    adjusted["cruise_speed"] *= scenario.speed_factor
                other = _evaluate_one(alternate, adjusted, result)
                if not other.valid:
                    raise ValueError(f"Invalid scenario {scenario.name}: {other.errors}")
                for key, margin in other.margins.items():
                    if margin < result.margins.get(key, float("inf")):
                        result.margins[key] = margin
                        result.limiting_scenarios[key] = scenario.name
                for i, value in enumerate(other.objectives):
                    if value > result.objectives[i]:
                        result.objectives[i] = value
                        result.limiting_scenarios[f"objective.{i}"] = scenario.name
                result.feasible = result.feasible and other.feasible
            result.warnings.append("Metrics show nominal conditions; objective values and margins show worst scenarios.")
        return result
    except (ValueError, KeyError, TypeError, ZeroDivisionError, OverflowError) as exc:
        return EvaluationResult(design=design, errors=[str(exc)])


def nondominated(results):
    feasible = [r for r in results if r.valid and r.feasible]
    unique = {}
    for r in feasible:
        unique[tuple(r.objectives)] = r
    feasible = list(unique.values())
    return [r for r in feasible if not any(all(a <= b for a, b in zip(other.objectives, r.objectives))
                                           and any(a < b for a, b in zip(other.objectives, r.objectives))
                                           for other in feasible)]


class _Stop(Exception):
    pass


class _Reserve(Exception):
    """Global search has used its share of the budget; local refinement may still run."""


def optimize(study, progress=None, cancel=None, checkpoint=None):
    import numpy as np
    study = deepcopy(study)
    study.validate()
    baseline = evaluate(study)
    free = [v for v in study.variables if v.free and v.lower < v.upper]
    result = OptimizationResult("running", baseline, input_hash=study.fingerprint(),
                                provenance={"seed": study.seed, "solver": study.solver,
                                            "budget": study.max_evaluations, "python": platform.python_version()})
    archive, cache = [], {}
    refining = False
    continuous = [v for v in free if not v.integer]
    reserve = 0
    if study.local_refinement and len(study.objectives) == 1 and continuous:
        reserve = min(25, max(8, study.max_evaluations // 5))
        if reserve >= study.max_evaluations:
            reserve = 0

    def sample(design):
        if cancel and cancel():
            result.status = "cancelled"
            raise _Stop()
        key = tuple(sorted((name, float(value)) for name, value in design.items()))
        if key in cache:
            return cache[key]
        cap = study.max_evaluations if refining else study.max_evaluations - reserve
        if result.evaluations >= cap:
            result.status = "budget_exhausted"
            raise _Stop() if refining or not reserve else _Reserve()
        r = evaluate(study, design)
        result.evaluations += 1
        if r.valid and r.feasible:
            archive[:] = nondominated(archive + [r])
        # Solver callbacks only need scalar results. Keep full histories for the
        # current front, not every rejected design in a large global search.
        if len(cache) >= 2048:
            cache.clear()
        cache[key] = replace(r, mission_history=[], endurance_history=[])
        row = dict(evaluation=result.evaluations, design=dict(design), valid=r.valid,
                   feasible=r.feasible, objectives=r.objectives, margins=r.margins,
                   errors=r.errors, metrics=r.metrics,
                   best_feasible_objectives=archive[0].objectives if len(study.objectives) == 1 and archive else None)
        result.history.append(row)
        if checkpoint:
            checkpoint(r)
        if progress:
            progress(row)
        return r

    def decode(x):
        return {v.key: float(round(value * v.scale) if v.integer else value * v.scale)
                for v, value in zip(free, x)}

    def score(x):
        r = sample(decode(x))
        return r.objectives[0] if r.valid else 1e30

    try:
        try:
            initial = sample({v.key: v.initial for v in free})
            if not free:
                result.status = "evaluated" if initial.valid else "invalid_evaluation"
                result.candidates = [initial]
                return result
            from scipy import __version__ as scipy_version
            from scipy.optimize import differential_evolution, minimize, NonlinearConstraint
            result.provenance.update(numpy=np.__version__, scipy=scipy_version)
            bounds = [(v.lower / v.scale, v.upper / v.scale) for v in free]
            # Integer coordinates use scale 1 so SciPy's integer constraint is physical.
            for i, v in enumerate(free):
                if v.integer:
                    v.scale = 1.
                    bounds[i] = (v.lower, v.upper)

            def violation(x):
                r = sample(decode(x))
                return min(r.margins.values(), default=0.) if r.valid else -1e10

            if len(study.objectives) > 1:
                import pymoo
                from pymoo.core.problem import ElementwiseProblem
                from pymoo.algorithms.moo.nsga2 import NSGA2
                from pymoo.optimize import minimize as moo_minimize
                result.provenance["pymoo"] = pymoo.__version__

                class Problem(ElementwiseProblem):
                    def __init__(self):
                        super().__init__(n_var=len(free), n_obj=len(study.objectives), n_ieq_constr=1,
                                         xl=np.array([b[0] for b in bounds]), xu=np.array([b[1] for b in bounds]))

                    def _evaluate(self, x, out, *args, **kwargs):
                        r = sample(decode(x))
                        out["F"] = r.objectives if r.valid else [1e30] * len(study.objectives)
                        out["G"] = [-min(r.margins.values(), default=0.) if r.valid else 1e10]

                moo_minimize(Problem(), NSGA2(pop_size=min(64, max(8, study.max_evaluations // 4))),
                             termination=("n_gen", 100000), seed=study.seed, verbose=False)
                result.status = "completed"
            elif study.solver == "slsqp":
                if any(v.integer for v in free):
                    raise ValueError("SLSQP requires continuous free variables")
                answer = minimize(score, [v.initial / v.scale for v in free], method="SLSQP", bounds=bounds,
                                  constraints=[{"type": "ineq", "fun": violation}],
                                  options={"maxiter": study.max_evaluations, "ftol": 1e-9})
                result.solver_message = str(answer.message)
                result.status = "completed" if answer.success else "solver_stopped"
            elif study.solver == "differential_evolution":
                answer = differential_evolution(score, bounds, rng=np.random.default_rng(study.seed),
                                                constraints=(NonlinearConstraint(violation, 0., np.inf),),
                                                x0=[v.initial / v.scale for v in free],
                                                integrality=[v.integer for v in free], polish=False,
                                                popsize=8, maxiter=study.max_evaluations, tol=1e-7)
                result.solver_message = str(answer.message)
                result.status = "completed" if answer.success else "solver_stopped"
            else:
                raise ValueError(f"Unknown solver {study.solver}")
        except _Reserve:
            pass
        if reserve and archive and len(study.objectives) == 1 and result.status != "cancelled":
            refining = True
            start = min(archive, key=lambda row: row.objectives[0])
            locked = {v.key: start.design[v.key] for v in free if v.integer}
            refined_bounds = [(v.lower, v.upper) for v in continuous]
            origin = [start.design[v.key] for v in continuous]

            def decode_refined(x):
                design = dict(locked)
                design.update({v.key: float(value) for v, value in zip(continuous, x)})
                return design

            def refined_score(x):
                row = sample(decode_refined(x))
                return row.objectives[0] if row.valid else 1e30

            def refined_margin(x):
                row = sample(decode_refined(x))
                return min(row.margins.values(), default=0.) if row.valid else -1e10

            polished = minimize(refined_score, origin, method="SLSQP", bounds=refined_bounds,
                                constraints=[{"type": "ineq", "fun": refined_margin}],
                                options={"maxiter": max(1, study.max_evaluations - result.evaluations), "ftol": 1e-9})
            result.provenance["local_refinement"] = "integers fixed; continuous variables polished with SLSQP"
            result.solver_message = (result.solver_message + " " if result.solver_message else "") + str(polished.message)
            if polished.success:
                result.status = "completed"
            elif result.status == "budget_exhausted":
                result.status = "solver_stopped"
    except _Stop:
        pass
    result.candidates = nondominated(archive)
    if not result.candidates and result.status not in ("cancelled", "budget_exhausted"):
        result.status = "no_feasible_design_found" if any(r["valid"] for r in result.history) else "invalid_evaluation"
    return result


def _study_sample(study, design, rows, progress, checkpoint, sized=None, sampled_inputs=None):
    result = _evaluate(study, design, sized)
    result.sampled_inputs = dict(sampled_inputs or {})
    rows.append(result)
    if checkpoint:
        checkpoint(result)
    if progress:
        progress(dict(evaluation=len(rows), design=dict(design), valid=result.valid,
                      feasible=result.feasible, objectives=result.objectives,
                      margins=result.margins, errors=result.errors, metrics=result.metrics))
    return result


def sweep(study, specification, progress=None, cancel=None, checkpoint=None):
    import numpy as np
    from scipy.stats import qmc
    variables = [v for v in study.variables if v.free and v.lower < v.upper]
    count = int(specification.get("samples", 25))
    if not 1 <= count <= 100000:
        raise ValueError("Samples must be between 1 and 100000")
    kind = specification.get("kind", "latin_hypercube")
    seed = specification.get("seed", study.seed)
    if kind == "grid":
        axes = specification.get("axes", {})
        if not set(axes) <= {v.key for v in variables}:
            raise ValueError("Grid axes must be free variables")
        total = math.prod(len(values) for values in axes.values())
        if total > 100000:
            raise ValueError("Grid exceeds 100000 evaluations")
        designs = [dict(zip(axes, values)) for values in itertools.product(*axes.values())]
    elif kind == "latin_hypercube":
        points = qmc.LatinHypercube(len(variables), seed=seed).random(count) if variables else np.zeros((1, 0))
        designs = [{v.key: float(round(v.lower + f * (v.upper - v.lower)) if v.integer else v.lower + f * (v.upper - v.lower))
                    for v, f in zip(variables, point)} for point in points]
    else:
        raise ValueError("Sweep kind must be grid or latin_hypercube")
    rows, status = [], "completed"
    for design in designs:
        if cancel and cancel():
            status = "cancelled"
            break
        _study_sample(study, design, rows, progress, checkpoint)
    return StudyResult(kind, rows, {"feasible_count": sum(r.feasible for r in rows)}, seed, study.fingerprint(), status)


def assess_uncertainty(study, design, specification, progress=None, cancel=None, checkpoint=None):
    import numpy as np
    seed = specification.get("seed", study.seed)
    rng = np.random.default_rng(seed)
    count = int(specification.get("samples", 100))
    if not 1 <= count <= 100000 or not specification.get("inputs"):
        raise ValueError("Specify uncertainty inputs and 1–100000 samples")
    nominal = evaluate(study, design)
    if not nominal.valid:
        raise ValueError("Uncertainty assessment needs a valid nominal design: " + "; ".join(nominal.errors))
    rows, status = [], "completed"
    for _ in range(count):
        if cancel and cancel():
            status = "cancelled"
            break
        alternate = deepcopy(study)
        sampled = {}
        for key, spec in specification["inputs"].items():
            # Uncertainty describes knowledge about assumptions, never changes owned hardware.
            if key not in alternate.vehicle.assumptions:
                raise ValueError(f"Unknown uncertain assumption {key}")
            kind = spec.get("distribution", "uniform")
            if kind == "uniform":
                value = rng.uniform(spec["lower"], spec["upper"])
            elif kind == "normal":
                if spec["std"] <= 0:
                    raise ValueError("Normal standard deviation must be positive")
                value = rng.normal(spec["mean"], spec["std"])
            else:
                raise ValueError("Uncertainty distribution must be uniform or normal")
            alternate.vehicle.assumptions[key] = float(value)
            sampled[key] = float(value)
        _study_sample(alternate, design, rows, progress, checkpoint, nominal, sampled)
    valid = [r for r in rows if r.valid]
    summary = {"sampled_feasibility": sum(r.feasible for r in rows) / len(rows) if rows else None,
               "invalid_count": len(rows) - len(valid), "requested_samples": count,
               "completed_samples": len(rows), "percentiles": {}}
    if valid:
        for metric in valid[0].metrics:
            summary["percentiles"][metric] = np.percentile([r.metrics[metric] for r in valid], [5, 50, 95]).tolist()
    return StudyResult("uncertainty", rows, summary, seed, study.fingerprint(), status)


def sensitivity(study, design=None, fraction=.01, progress=None, cancel=None, checkpoint=None):
    if not 0 < fraction < .5:
        raise ValueError("Sensitivity fraction must be in (0, 0.5)")
    base = dict(design or {})
    rows, derivatives = [], {}
    status = "completed"
    for v in study.variables:
        if not v.free or v.integer or v.lower == v.upper:
            continue
        x = base.get(v.key, v.initial)
        step = fraction * (v.upper - v.lower)
        lower, upper = max(v.lower, x - step), min(v.upper, x + step)
        if cancel and cancel():
            status = "cancelled"
            break
        lo = _study_sample(study, {**base, v.key: lower}, rows, progress, checkpoint)
        if cancel and cancel():
            status = "cancelled"
            break
        hi = _study_sample(study, {**base, v.key: upper}, rows, progress, checkpoint)
        if lo.valid and hi.valid:
            derivatives[v.key] = {k: (hi.metrics[k] - lo.metrics[k]) / (upper - lower) for k in lo.metrics}
    return StudyResult("sensitivity", rows, derivatives, study.seed, study.fingerprint(), status)
