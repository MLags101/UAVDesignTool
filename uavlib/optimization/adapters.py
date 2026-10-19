"""Optional comparison adapters. Imports are isolated from the default workbench.

Comparisons never replace the core result or imply agreement. Extra geometry and
inertia required by an external solver must be supplied explicitly in config.
"""
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import hashlib
import math
import os
from .schema import MODEL_VERSION


def compare(backend, study, candidate, config):
    if not candidate.valid:
        raise ValueError("Select a valid candidate for external comparison")
    if backend not in ("aerosandbox", "openvsp", "rocketpy"):
        raise ValueError("Unknown comparison backend")
    functions = {"aerosandbox": _aerosandbox, "openvsp": _openvsp, "rocketpy": _rocketpy}
    try:
        metrics, notes = functions[backend](study, candidate, config)
    except ImportError as exc:
        raise RuntimeError(f"Install {backend} in the comparison worker's Python environment") from exc
    try:
        external_version = version(backend)
    except PackageNotFoundError:
        external_version = config.get("version", "unreported")
    return dict(backend=backend, version=external_version, input_hash=study.fingerprint(),
                model_version=MODEL_VERSION, design=candidate.design, config=config,
                metrics=metrics, notes=notes, differences={k: v - candidate.metrics[k]
                    for k, v in metrics.items() if k in candidate.metrics})


def _aerosandbox(study, candidate, config):
    import aerosandbox as asb
    if study.vehicle.family not in ("fixed_wing", "lift_cruise"):
        raise ValueError("AeroSandbox adapter supports winged configurations")
    p = candidate.design
    span = math.sqrt(p["wing_area"] * p["aspect_ratio"])
    chord = p["wing_area"] / span
    airfoil = asb.Airfoil(name=config["airfoil"])
    wing = asb.Wing(name="Main wing", symmetric=True, xsecs=[
        asb.WingXSec(xyz_le=[0, 0, 0], chord=chord, airfoil=airfoil),
        asb.WingXSec(xyz_le=[0, span / 2, 0], chord=chord, airfoil=airfoil)])
    airplane = asb.Airplane(name=study.name, xyz_ref=[candidate.metrics["cg"], 0, 0], wings=[wing])
    point = asb.OperatingPoint(atmosphere=asb.Atmosphere(altitude=config.get("altitude", 0)),
                              velocity=p["cruise_speed"], alpha=config["alpha_degrees"])
    answer = asb.AeroBuildup(airplane=airplane, op_point=point).run()
    return {k: float(answer[k]) for k in ("CL", "CD", "Cm", "L", "D")}, [
        "Rectangular main-wing aerodynamic comparison only; fuselage, tail and lift-rotor installation are excluded.",
        "Angle of attack supplied explicitly; this comparison is not a trimmed full-aircraft validation."]


def _openvsp(study, candidate, config):
    import openvsp as vsp
    if study.vehicle.family not in ("fixed_wing", "lift_cruise"):
        raise ValueError("VSPAERO adapter supports winged configurations")
    source = Path(config["model_path"]).resolve()
    working = Path(config["working_directory"]).resolve()
    working.mkdir(parents=True, exist_ok=True)
    old = Path.cwd()
    try:
        os.chdir(working)
        vsp.ClearVSPModel()
        vsp.ReadVSPFile(str(source))
        if "vspaero_path" in config and not vsp.SetVSPAEROPath(str(Path(config["vspaero_path"]).resolve())):
            raise ValueError("VSPAERO executable directory is invalid")
        # Mappings bind a study design field to a user-prepared VSP parameter.
        expected = {}
        for key, binding in config["parameter_bindings"].items():
            if key not in candidate.design:
                raise ValueError(f"Unknown VSP binding {key}")
            parameter_id = binding["id"] if isinstance(binding, dict) else binding
            target = candidate.design[key] * binding.get("scale", 1.) + binding.get("offset", 0.) if isinstance(binding, dict) else candidate.design[key]
            if not math.isfinite(target):
                raise ValueError(f"Nonfinite VSP binding for {key}")
            if not vsp.ValidParm(parameter_id):
                raise ValueError(f"Unknown VSP parameter ID for {key}")
            vsp.SetParmVal(parameter_id, target)
            vsp.Update()
            expected[key] = (parameter_id, target)
        vsp.Update()
        for key, (parameter_id, target) in expected.items():
            if not math.isclose(vsp.GetParmVal(parameter_id), target, rel_tol=1e-8, abs_tol=1e-10):
                raise ValueError(f"VSP geometry drivers or bounds changed requested {key}")
        # ReadVSPFile sets the active filename to the source. Redirect generated
        # geometry/solver products before running any analysis.
        prepared = working / "candidate.vsp3"
        if prepared == source:
            raise ValueError("Comparison working file must differ from source geometry")
        vsp.SetVSP3FileName(str(prepared))
        vsp.WriteVSPFile(str(prepared), vsp.SET_ALL)
        vsp.SetAnalysisInputDefaults("VSPAEROComputeGeometry")
        for key, values in config.get("geometry_integer_inputs", {}).items():
            if key not in vsp.GetAnalysisInputNames("VSPAEROComputeGeometry"):
                raise ValueError(f"Unknown geometry analysis input: {key}")
            vsp.SetIntAnalysisInput("VSPAEROComputeGeometry", key, values)
        vsp.ExecAnalysis("VSPAEROComputeGeometry")
        name = "VSPAEROSweep"
        vsp.SetAnalysisInputDefaults(name)
        for key, values in config.get("double_inputs", {}).items():
            if key not in vsp.GetAnalysisInputNames(name):
                raise ValueError(f"Unknown VSPAERO input: {key}")
            vsp.SetDoubleAnalysisInput(name, key, values)
        for key, values in config.get("integer_inputs", {}).items():
            if key not in vsp.GetAnalysisInputNames(name):
                raise ValueError(f"Unknown VSPAERO input: {key}")
            vsp.SetIntAnalysisInput(name, key, values)
        vsp.ExecAnalysis(name)
        result_id = vsp.FindLatestResultsID(config.get("result_type", "VSPAERO_History"))
        if not result_id:
            raise ValueError("VSPAERO produced no history results")
        metrics = {}
        for label, field in config.get("result_fields", {"CL": "CLtot", "CD": "CDtot"}).items():
            values = vsp.GetDoubleResults(result_id, field)
            if not values:
                raise ValueError(f"VSPAERO result field unavailable: {field}")
            metrics[label] = float(values[-1])
        return metrics, ["User-prepared geometry; verify reference areas and analysis settings.",
                         "Source geometry SHA256: " + hashlib.sha256(source.read_bytes()).hexdigest()]
    finally:
        os.chdir(old)


def _rocketpy(study, candidate, config):
    from rocketpy import Environment, GenericMotor, Rocket, Flight
    if study.vehicle.family != "rocket":
        raise ValueError("RocketPy adapter requires a rocket study")
    # A full external-model configuration is required because 6-DOF inertia,
    # coordinate orientation and motor geometry are absent from a point-mass model.
    environment = Environment(**config["environment"])
    environment.set_atmospheric_model(type="standard_atmosphere")
    motor = GenericMotor(**config["motor"])
    rocket = Rocket(**config["rocket"])
    rocket.add_motor(motor, position=config["motor_position"])
    if "nose" in config:
        rocket.add_nose(**config["nose"])
    if "fins" in config:
        rocket.add_trapezoidal_fins(**config["fins"])
    if "parachute" in config:
        rocket.add_parachute(**config["parachute"])
    flight = Flight(rocket=rocket, environment=environment, **config["flight"])
    return {"apogee": float(flight.apogee - environment.elevation)}, [
        "External geometry, inertia and motor configuration were explicitly supplied.",
        "Confirm external mass, thrust and geometry match the selected core candidate before comparing apogee."]
