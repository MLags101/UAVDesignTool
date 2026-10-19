"""Independent published-data gate; exits nonzero when the model misses tolerance.

Unlike regression tests, this deliberately preserves an unmet qualification gate.
Run from the repository root with the core numerical environment.
"""
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uavlib.optimization.physics import rotor_performance
from uavlib.optimization.schema import MODEL_VERSION
from uavlib.optimization.storage import atomic_json


def main():
    path = Path(__file__).parent / "fixtures/optimization/caradonna-tung.json"
    fixture = json.loads(path.read_text())
    inputs, assumptions = fixture["inputs"], fixture["model_assumptions"]
    radius = assumptions["normalized_radius_m"]
    tip_speed = inputs["tip_mach"] * assumptions["sound_speed_m_s"]
    density = assumptions["density_kg_m3"]
    thrust = inputs["thrust_coefficient"] * density * math.pi * radius**2 * tip_speed**2
    result = rotor_performance(thrust, 0., density, radius,
                               tip_speed / radius * 60 / (2 * math.pi),
                               inputs["blade_count"], radius / inputs["radius_to_chord"],
                               assumptions["profile_cd"], assumptions["lift_slope_per_radian"])
    prediction = math.degrees(result["collective"])
    error = prediction - fixture["expected_collective_degrees"]
    report = dict(model_version=MODEL_VERSION, reference=fixture,
                  predicted_collective_degrees=prediction, error_degrees=error,
                  accepted=abs(error) <= fixture["absolute_tolerance_degrees"])
    atomic_json(Path("build/reference-validation/caradonna-tung.json"), report)
    print(json.dumps(report, indent=2))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
