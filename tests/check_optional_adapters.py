"""Run in a separate environment with AeroSandbox and RocketPy installed.

These smoke cases verify real API execution, not aircraft engineering accuracy.
"""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uavlib.optimization import template, evaluate
from uavlib.optimization.adapters import compare


def main():
    wing = template()
    candidate = evaluate(wing)
    aero = compare("aerosandbox", wing, candidate, {"airfoil": "naca0012", "alpha_degrees": 5., "altitude": 0.})
    assert aero["metrics"]["CL"] > 0 and aero["metrics"]["CD"] > 0, aero
    print("PASS AeroSandbox", aero["version"], aero["metrics"], flush=True)

    study = template("rocket")
    candidate = evaluate(study)
    parts = candidate.mass_breakdown
    config = {
        "environment": {"latitude": 0, "longitude": 0, "elevation": 0},
        "motor": {"thrust_source": .15 * 9.80665 * 170 / 2, "burn_time": 2.,
                  "chamber_radius": .02, "chamber_height": .2, "chamber_position": 0,
                  "propellant_initial_mass": .15, "nozzle_radius": .005,
                  "dry_mass": parts["motor"], "dry_inertia": [.0003, .0003, .00001]},
        "rocket": {"radius": .04, "mass": parts["payload"] + parts["airframe"] + parts["recovery"],
                   "inertia": [.08, .08, .002], "power_off_drag": .45, "power_on_drag": .45,
                   "center_of_mass_without_motor": .6, "coordinate_system_orientation": "tail_to_nose"},
        "motor_position": .15,
        "nose": {"length": .2, "kind": "conical", "position": 1.2},
        "fins": {"n": 4, "root_chord": .12, "tip_chord": .12, "span": .1, "position": .25},
        "parachute": {"name": "main", "cd_s": .9, "trigger": "apogee", "sampling_rate": 100, "lag": 0},
        "flight": {"rail_length": 2., "inclination": 90., "heading": 0., "max_time": 1200.},
    }
    rocket = compare("rocketpy", study, candidate, config)
    assert rocket["metrics"]["apogee"] > 0, rocket
    fixture = json.loads((Path(__file__).parent / "fixtures/optimization/rocketpy-vertical.json").read_text())
    assert abs(rocket["metrics"]["apogee"] - candidate.metrics["apogee"]) <= fixture["tolerances"]["apogee_absolute_m"], rocket
    print("PASS RocketPy", rocket["version"], rocket["metrics"], flush=True)
    folder = Path("build/adapter-validation")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "comparisons.json").write_text(json.dumps([aero, rocket], indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
