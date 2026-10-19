"""Reproducible conceptual studies; run from the repository root.

python examples/optimization_studies.py fixed_wing --budget 100
"""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uavlib.optimization import template, optimize, Objective
from uavlib.optimization.storage import export_study


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("family", choices=["fixed_wing", "multirotor", "helicopter", "lift_cruise", "rocket"])
    parser.add_argument("--budget", type=int, default=100)
    parser.add_argument("--pareto", action="store_true")
    parser.add_argument("--output", default="build/example-study")
    args = parser.parse_args()
    study = template(args.family)
    study.max_evaluations = args.budget
    if args.pareto:
        study.objectives.append(Objective("apogee" if args.family == "rocket" else "installed_power", "max" if args.family == "rocket" else "min", 100.))
    result = optimize(study)
    export_study(study, args.output, result)
    print(result.status, result.evaluations, len(result.candidates), "feasible candidate(s)")


if __name__ == "__main__":
    main()
