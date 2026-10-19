"""Generate ten reproducible tutorial studies and verify forward equivalence.

Hardware fixtures are synthetic locked conceptual assemblies, not manufacturer
data. Replace their records/maps with your own measured parts before real use.
"""
from copy import deepcopy
from pathlib import Path
import math
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uavlib.optimization import template, evaluate, ComponentDefinition, Objective
from uavlib.optimization.storage import atomic_json


def locked_example(study, baseline):
    fixed = deepcopy(study)
    fixed.workflow = "hardware"
    fixed.name += " — locked conceptual example"
    fixed.variables = []
    fixed.objectives = [Objective("apogee" if fixed.vehicle.family == "rocket" else "endurance", "max")]
    fixed.vehicle.parameters.update({k: v for k, v in baseline.design.items() if not k.startswith("_")})
    p, a, m = fixed.vehicle.parameters, fixed.vehicle.assumptions, baseline.metrics
    parts = []

    def add(identity, kind, mass=0., quantity=1, position=0., **properties):
        parts.append(ComponentDefinition(identity, kind, mass, quantity, position, properties,
                                         "Synthetic tutorial correlation; replace with measured hardware", True))

    family = fixed.vehicle.family
    if family == "rocket":
        thrust = p["propellant_mass"] * 9.80665 * a["specific_impulse"] / p["burn_time"]
        add("motor", "rocket_motor", baseline.mass_breakdown["motor"], position=.85*p["body_length"],
            thrust_curve=[[0,thrust],[p["burn_time"],thrust]], propellant_curve=[[0,p["propellant_mass"]],[p["burn_time"],0.]])
    else:
        position = .3 * math.sqrt(p["wing_area"] / p["aspect_ratio"])
        add("motor", "motor", baseline.mass_breakdown["propulsion"], position=position, max_power=m["cruise_installed_power"])
        add("battery", "battery", baseline.mass_breakdown["storage"], position=position,
            energy=m["energy_capacity"], voltage=a["voltage"], resistance=a["resistance"], min_voltage=a["min_voltage"], max_current=a["max_current"])
        add("controller", "controller", max_current=a["max_current"])
        if family != "helicopter":
            add("propeller", "propeller", quantity=4 if family == "multirotor" else 1,
                diameter=p["rotor_diameter"], efficiency_map=[[0,a["efficiency"]],[40,a["efficiency"]]],
                max_power_map=[[0,m["cruise_installed_power"]],[40,m["cruise_installed_power"]]])
        if family in ("helicopter", "lift_cruise"):
            add("rotor", "main_rotor" if family == "helicopter" else "lift_rotor", quantity=1 if family == "helicopter" else 4,
                diameter=p["rotor_diameter"], chord=p["blade_chord"], blades=p["blade_count"], rpm=p["rotor_rpm"])
        if family == "helicopter":
            add("tail", "tail_rotor", diameter=p["tail_rotor_diameter"])
            add("transmission", "transmission", max_power=m["cruise_installed_power"])
        if family == "lift_cruise":
            add("lift_motor", "lift_motor", max_power=m["installed_lift_power"])
    fixed.vehicle.components = parts
    return fixed


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build/workflow-tutorials")
    for family in ("fixed_wing", "multirotor", "helicopter", "lift_cruise", "rocket"):
        study = template(family)
        baseline = evaluate(study)
        assert baseline.valid, baseline.errors
        hardware = locked_example(study, baseline)
        fixed = evaluate(hardware)
        assert fixed.valid, fixed.errors
        assert abs(fixed.metrics["takeoff_mass"] - baseline.metrics["takeoff_mass"]) < 1e-4
        metric = "apogee" if family == "rocket" else "energy_required"
        assert abs(fixed.metrics[metric] - baseline.metrics[metric]) < 1.
        for name, definition, result in (("requirements", study, baseline), ("hardware", hardware, fixed)):
            atomic_json(output / family / name / "study.json", definition.to_dict())
            atomic_json(output / family / name / "evaluation.json", result.to_dict())
        print(f"PASS {family}: both workflows agree; mass {baseline.metrics['takeoff_mass']:.6f} kg", flush=True)


if __name__ == "__main__":
    main()
