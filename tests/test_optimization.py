"""Reference and integration tests for the conceptual workbench."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy

from uavlib.optimization import *
from uavlib.optimization.physics import atmosphere, battery_operating_point, ideal_hover, interpolate
from uavlib.optimization.engine import nondominated
from uavlib.optimization.vehicles import register_model
from uavlib.optimization.storage import StudyStore, atomic_json, export_study
from uav_app.models import ProjectModel


class AnalyticModel:
    parameters = {"x": ("", "dimensionless")}
    metrics = {"f": "", "g": "", "x": ""}

    def evaluate(self, study, p):
        x = p["x"]
        return EvaluationResult(design=p, metrics={"x": x, "f": (x - 2) ** 2, "g": x * x},
                                valid=True, converged=True)


class MixedModel:
    parameters = {"x": ("", "dimensionless"), "n": ("", "count")}
    metrics = {"f": "", "x": "", "n": ""}

    def evaluate(self, study, p):
        return EvaluationResult(design=p, metrics={"x": p["x"], "n": p["n"], "f": (p["x"] - 0.2) ** 2},
                                valid=True, converged=True)


register_model("analytic", AnalyticModel())
register_model("mixed", MixedModel())


def analytic():
    return StudyDefinition(vehicle=VehicleDefinition("analytic", parameters={"x": 0}),
                           variables=[DesignVariable("x", .5, 0, 3)],
                           requirements=[Requirement("x", 1, "<=")], objectives=[Objective("f")],
                           max_evaluations=200)


class TestReferencePhysics(unittest.TestCase):
    def test_atmosphere_reference(self):
        self.assertAlmostEqual(atmosphere(0).density, 1.225, places=3)
        self.assertAlmostEqual(atmosphere(11000).temperature, 216.65, places=2)
        self.assertAlmostEqual(atmosphere(20000).pressure, 5474.89, delta=10)
        self.assertGreater(atmosphere(84852).density, 0)
        with self.assertRaises(ValueError):
            atmosphere(90000)

    def test_hover_reference(self):
        self.assertAlmostEqual(ideal_hover(10, 1.225, 1), 20.203050891, places=8)

    def test_axial_climb_contains_potential_power_once(self):
        from uavlib.optimization.physics import axial_induced_power
        hover_power, induced = axial_induced_power(10, 0, 1.225, 1)
        self.assertAlmostEqual(hover_power, ideal_hover(10, 1.225, 1), places=8)
        climb = 2.0
        power, induced = axial_induced_power(10, climb, 1.225, 1)
        hover_induced = math.sqrt(10 / (2 * 1.225 * 1))
        self.assertLess(induced, hover_induced)
        self.assertAlmostEqual(power, 10 * (climb + induced), places=8)
        # Adding weight*climb on top of hover induced power double-counts the climb.
        self.assertLess(power, 10 * hover_induced + 10 * climb)

    def test_battery_reference(self):
        current, voltage = battery_operating_point(360, 20, .1)
        self.assertAlmostEqual(current, 20)
        self.assertAlmostEqual(voltage, 18)
        with self.assertRaises(ValueError):
            battery_operating_point(1001, 20, .1)

    def test_map_domain_and_monotonic_coordinates(self):
        self.assertEqual(interpolate([[0, 0], [2, 4]], 1), 2)
        for points, x in (([[0, 0], [2, 4]], 3), ([[0, 0], [0, 4]], 0)):
            with self.assertRaises(ValueError):
                interpolate(points, x)


class TestStudyAndSolvers(unittest.TestCase):
    def test_roundtrip_hash(self):
        s = template()
        self.assertEqual(s.fingerprint(), StudyDefinition.from_dict(s.to_dict()).fingerprint())
        other = deepcopy(s)
        other.vehicle.assumptions["cd0"] += .001
        self.assertNotEqual(s.fingerprint(), other.fingerprint())

    def test_slsqp_known_constrained_solution(self):
        s = analytic()
        s.solver = "slsqp"
        r = optimize(s)
        self.assertTrue(r.candidates)
        best = r.candidates[0]
        self.assertAlmostEqual(best.metrics["x"], 1, delta=.001)
        self.assertAlmostEqual(best.metrics["f"], 1, delta=.001)

    def test_fixed_no_solver(self):
        s = analytic()
        s.variables[0].free = False
        r = optimize(s)
        self.assertEqual(r.status, "evaluated")
        self.assertEqual(r.evaluations, 1)
        self.assertFalse(evaluate(s, {"x": .8}).valid)

    def test_local_refinement_keeps_integers_fixed(self):
        study = StudyDefinition(
            vehicle=VehicleDefinition("mixed", parameters={"x": 1.5, "n": 1}),
            variables=[DesignVariable("x", 1.5, 0, 2),
                       DesignVariable("n", 1, 0, 3, integer=True)],
            requirements=[Requirement("x", 0.2, "<=")],
            objectives=[Objective("f")], max_evaluations=80, local_refinement=True)
        result = optimize(study)
        self.assertTrue(result.candidates, result.status)
        best = result.candidates[0]
        self.assertAlmostEqual(best.metrics["x"], 0.2, delta=1e-3)
        self.assertEqual(best.metrics["n"], int(best.metrics["n"]))
        self.assertIn(result.provenance.get("local_refinement"), ("integers fixed; continuous variables polished with SLSQP",))

    def test_integer_and_reproducible(self):
        s = analytic()
        s.variables[0].initial = 0
        s.variables[0].integer = True
        one, two = optimize(s), optimize(s)
        self.assertEqual(one.history, two.history)
        self.assertTrue(one.candidates)
        self.assertEqual(one.candidates[0].metrics["x"], 1)

    def test_cancellation(self):
        count = []
        r = optimize(analytic(), lambda row: count.append(row), lambda: len(count) >= 3)
        self.assertEqual(r.status, "cancelled")
        self.assertEqual(r.evaluations, 3)

    def test_pareto(self):
        s = analytic()
        s.requirements = []
        s.variables[0].upper = 2
        s.objectives = [Objective("f"), Objective("g")]
        s.max_evaluations = 80
        r = optimize(s)
        self.assertGreater(len(r.candidates), 2)
        self.assertTrue(all(c.feasible for c in r.candidates))
        self.assertEqual(len(nondominated(r.candidates)), len(r.candidates))

    def test_infeasible_not_success(self):
        s = analytic()
        s.requirements = [Requirement("x", -10, "<=")]
        s.max_evaluations = 20
        r = optimize(s)
        self.assertFalse(r.candidates)
        self.assertNotEqual(r.status, "completed")

    def test_unknown_metric_and_nan(self):
        s = template()
        s.objectives = [Objective("unknown")]
        self.assertFalse(evaluate(s).valid)
        s = template()
        s.vehicle.assumptions["cd0"] = float("nan")
        self.assertFalse(evaluate(s).valid)

    def test_sweep(self):
        r = sweep(analytic(), {"kind": "grid", "axes": {"x": [0, .5, 1, 2]}})
        self.assertEqual(len(r.evaluations), 4)
        self.assertEqual(r.summary["feasible_count"], 3)

    def test_uncertainty_and_sensitivity(self):
        s = template()
        spec = {"samples": 3, "inputs": {"cd0": {"lower": .03, "upper": .04}}}
        self.assertEqual(assess_uncertainty(s, {}, spec).to_dict(), assess_uncertainty(s, {}, spec).to_dict())
        r = sensitivity(s)
        self.assertIn("wing_area", r.summary)


class TestVehicleModels(unittest.TestCase):
    def test_helicopter_tail_power_and_trim(self):
        r = evaluate(template("helicopter"))
        self.assertTrue(r.valid, r.errors)
        self.assertTrue(r.feasible, r.margins)
        self.assertGreater(r.metrics["tail_rotor_power"], 0)

    def test_fuel_lift_cruise_accounts_both_stores(self):
        r = evaluate(template("lift_cruise", propulsion="fuel"))
        self.assertTrue(r.valid, r.errors)
        self.assertGreater(r.metrics["energy_required"], 0)
        self.assertGreater(r.metrics["fuel_used"], 0)
        self.assertGreater(r.metrics["installed_lift_power"], 0)

    def test_requirements_to_hardware_same_aircraft(self):
        for family in ("fixed_wing", "multirotor", "helicopter", "lift_cruise"):
            with self.subTest(family=family):
                s = template(family)
                baseline = evaluate(s)
                self.assertTrue(baseline.valid, baseline.errors)
                s.workflow = "hardware"
                s.variables = []
                s.vehicle.parameters.update({k: v for k, v in baseline.design.items() if not k.startswith("_")})
                a, p, m = s.vehicle.assumptions, s.vehicle.parameters, baseline.metrics
                count = 1 if family in ("fixed_wing", "helicopter") else 4
                parts = [ComponentDefinition("motor", "motor", baseline.mass_breakdown["propulsion"],
                                             position=.3 * math.sqrt(p["wing_area"] / p["aspect_ratio"]),
                                             properties={"max_power": m["cruise_installed_power"]}),
                         ComponentDefinition("battery", "battery", baseline.mass_breakdown["storage"],
                                             position=.3 * math.sqrt(p["wing_area"] / p["aspect_ratio"]),
                                             properties={"energy": m["energy_capacity"], "voltage": a["voltage"],
                                                         "resistance": a["resistance"], "min_voltage": a["min_voltage"],
                                                         "max_current": a["max_current"]}),
                         ComponentDefinition("esc", "controller", 0., properties={"max_current": a["max_current"]})]
                if family != "helicopter":
                    parts.append(ComponentDefinition("prop", "propeller", 0., quantity=count if family == "multirotor" else 1,
                        properties={"diameter": p["rotor_diameter"], "efficiency_map": [[0, a["efficiency"]], [40, a["efficiency"]]],
                                    "max_power_map": [[0, m["cruise_installed_power"]], [40, m["cruise_installed_power"]]]}))
                if family in ("helicopter", "lift_cruise"):
                    parts.append(ComponentDefinition("rotor", "main_rotor" if family == "helicopter" else "lift_rotor", 0., quantity=count,
                        properties={"diameter": p["rotor_diameter"], "chord": p["blade_chord"], "blades": p["blade_count"], "rpm": p["rotor_rpm"]}))
                if family == "helicopter":
                    parts += [ComponentDefinition("tail", "tail_rotor", 0., properties={"diameter": p["tail_rotor_diameter"]}),
                              ComponentDefinition("gear", "transmission", 0., properties={"max_power": m["cruise_installed_power"]})]
                if family == "lift_cruise":
                    parts.append(ComponentDefinition("lift", "lift_motor", 0., properties={"max_power": m["installed_lift_power"]}))
                s.vehicle.components = parts
                r = evaluate(s)
                self.assertTrue(r.valid, r.errors)
                self.assertAlmostEqual(r.metrics["takeoff_mass"], m["takeoff_mass"], delta=1e-4)
                self.assertAlmostEqual(r.metrics["energy_required"], m["energy_required"], delta=1.)

    def test_robust_scenario_does_not_resize_battery(self):
        s = template()
        nominal = evaluate(s)
        s.robust = True
        s.scenarios = [OperatingScenario("Heavy", payload_delta=1.)]
        r = evaluate(s)
        self.assertTrue(r.valid, r.errors)
        self.assertLess(r.margins["energy"], nominal.margins["energy"])
        self.assertEqual(r.metrics["energy_capacity"], nominal.metrics["energy_capacity"])
        self.assertFalse(r.feasible)

    def test_segment_power_requirement(self):
        s = template()
        s.requirements.append(Requirement("peak_power", 1., "<=", segment="Cruise"))
        r = evaluate(s)
        self.assertTrue(r.valid, r.errors)
        self.assertFalse(r.feasible)
        self.assertLess(r.margins["requirement.1.peak_power"], 0)

    def test_aircraft_closure(self):
        for family in ("fixed_wing", "multirotor", "lift_cruise"):
            with self.subTest(family=family):
                r = evaluate(template(family))
                self.assertTrue(r.valid, r.errors)
                self.assertTrue(r.feasible, r.margins)
                self.assertLess(r.closure_residual, 1e-4)
                self.assertAlmostEqual(sum(r.mass_breakdown.values()), r.metrics["takeoff_mass"], delta=1e-4)
                self.assertGreater(r.metrics["energy_required"], 0)
                if family == "lift_cruise":
                    self.assertGreater(r.metrics["transition_energy"], 0)

    def test_fuel_mass_evolves(self):
        s = template(propulsion="fuel")
        r = evaluate(s)
        self.assertTrue(r.valid, r.errors)
        self.assertGreater(r.metrics["fuel_used"], 0)
        self.assertGreater(r.mission_history[0]["mass"], r.mission_history[-1]["mass"])

    def test_hardware_requires_data_and_locks_dimensions(self):
        s = template(workflow="hardware")
        self.assertFalse(evaluate(s).valid)
        s.vehicle.components = [ComponentDefinition("battery", "battery", .5), ComponentDefinition("prop", "propeller", .1)]
        s.variables.append(DesignVariable("rotor_diameter", .5, .2, .8))
        before = s.to_dict()
        result = evaluate(s)
        self.assertFalse(result.valid)
        self.assertIn("Hardware locks", result.errors[0])
        self.assertEqual(before, s.to_dict())

    def test_fixed_hardware_forward(self):
        s = template(workflow="hardware")
        s.vehicle.components = [
            ComponentDefinition("drive", "motor", .15, properties={"max_power": 500}),
            ComponentDefinition("pack", "battery", .6, properties={"energy": 450000, "voltage": 22.2,
                                "resistance": .025, "max_current": 70, "min_voltage": 18}),
            ComponentDefinition("esc", "controller", .04, properties={"max_current": 70}),
            ComponentDefinition("prop", "propeller", .03, properties={"diameter": .3,
                                "efficiency_map": [[0, .5], [40, .8]], "max_power_map": [[0, 500], [40, 500]]}),
        ]
        before = s.to_dict()
        r = evaluate(s)
        self.assertTrue(r.valid, r.errors)
        self.assertEqual(before, s.to_dict())
        for v in s.variables:
            v.free = False
        self.assertEqual(optimize(s).status, "evaluated")

    def test_robust_margins(self):
        s = template()
        nominal = evaluate(s)
        s.robust = True
        s.scenarios = [OperatingScenario("High field", 2000, 1, .2)]
        robust = evaluate(s)
        self.assertTrue(robust.valid, robust.errors)
        self.assertGreaterEqual(robust.objectives[0], nominal.objectives[0])
        for key in nominal.margins:
            self.assertLessEqual(robust.margins[key], nominal.margins[key] + 1e-10)

    def test_rocket_events_and_mass(self):
        r = evaluate(template("rocket"))
        self.assertTrue(r.valid, r.errors)
        self.assertGreater(r.metrics["apogee"], 0)
        self.assertGreater(r.metrics["guide_exit_speed"], 0)
        self.assertAlmostEqual(r.mission_history[-1]["altitude"], 0, delta=1e-5)
        self.assertGreater(r.mission_history[0]["mass"], r.mission_history[-1]["mass"])

    def test_rocket_rejects_supersonic_surrogate(self):
        s = template("rocket")
        s.vehicle.assumptions["rocket_max_mach"] = .05
        r = evaluate(s)
        self.assertFalse(r.valid)
        self.assertIn("aerodynamic domain", r.errors[0])


class TestProjectStorage(unittest.TestCase):
    def test_csv_no_skipped_rows(self):
        from uavlib.optimization.data import read_curve_csv
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "curve.csv"
            path.write_text("x,y\n0,10\n1,20\n")
            self.assertEqual(read_curve_csv(path), [[0., 10.], [1., 20.]])
            path.write_text("x,y\n0,10\nbad,20\n")
            with self.assertRaises(ValueError):
                read_curve_csv(path)

    def test_legacy_migration_and_future_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "project.json"
            path.write_text(json.dumps({"version": 2, "name": "Old"}))
            model = ProjectModel()
            model.load_project(str(path))
            model.save_project()
            self.assertTrue(Path(str(path) + ".v2.bak").exists())
            self.assertEqual(json.loads(path.read_text())["version"], 3)
            path.write_text('{"version": 99}')
            with self.assertRaises(ValueError):
                model.load_project(str(path))

    def test_snapshots_export_and_staleness(self):
        with tempfile.TemporaryDirectory() as folder:
            store = StudyStore(folder)
            s = analytic()
            s.variables[0].free = False
            r = optimize(s)
            path = store.save_study(s)
            self.assertEqual(store.load_study(path).fingerprint(), s.fingerprint())
            run = store.save_run(s, r)
            self.assertTrue((Path(folder) / run / "result.json").exists())
            self.assertFalse(store.stale(s, r.to_dict()))
            s.name = "Changed"
            self.assertTrue(store.stale(s, r.to_dict()))
            export_study(s, Path(folder) / "export", r)
            self.assertTrue((Path(folder) / "export" / "candidates.csv").exists())
            with self.assertRaises(ValueError):
                store.load_study("../outside.json")

    def test_worker_process(self):
        with tempfile.TemporaryDirectory() as folder:
            atomic_json(Path(folder) / "request.json", {"study": template().to_dict(), "mode": "evaluate"})
            process = subprocess.run([sys.executable, "-B", "-m", "uavlib.optimization.worker", folder],
                                     capture_output=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(json.loads((Path(folder) / "result.json").read_text())["result"]["valid"])


if __name__ == "__main__":
    unittest.main()
