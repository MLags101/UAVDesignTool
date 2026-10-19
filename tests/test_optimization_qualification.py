"""Independent equation fixtures and durable execution acceptance checks."""
import json
from pathlib import Path
import tempfile
import unittest

from uavlib.optimization import template, evaluate, sweep, assess_uncertainty, ComponentDefinition
from uavlib.optimization.engine import sensitivity
from uavlib.optimization.physics import rotor_performance, transition_forces, helicopter_trim
from uavlib.optimization.storage import atomic_json
from uavlib.optimization.worker import recover, execute
from uavlib.optimization.schema import MODEL_VERSION


class TestRotorTrim(unittest.TestCase):
    def test_aircraft_six_component_equilibrium(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/optimization/helicopter-equilibrium.json").read_text())
        for case in fixture["cases"]:
            result = helicopter_trim(**case, climb=0., rho=1.225, radius=.8, rpm=1300,
                                     blades=2, chord=.06, cd0=.012, tail_arm=1.1)
            for prefix in ("force_residual_", "moment_residual_"):
                for axis in "xyz":
                    self.assertAlmostEqual(result[prefix + axis], 0, delta=fixture["absolute_tolerance"])
            self.assertGreater(result["tail_thrust"], 0)
    def test_predeclared_equilibrium_cases(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/optimization/rotor-trim.json").read_text())
        for case in fixture["cases"]:
            with self.subTest(case=case):
                inputs = {**fixture["inputs"], **{k: v for k, v in case.items() if k != "expected_cyclic"}}
                result = rotor_performance(**inputs)
                self.assertAlmostEqual(result["thrust"], inputs["thrust"], delta=fixture["tolerances"]["thrust_N"])
                for key in ("roll_moment", "pitch_moment"):
                    self.assertAlmostEqual(result[key], inputs[key], delta=fixture["tolerances"]["moment_Nm"])
                if "expected_cyclic" in case:
                    for key in ("cyclic_cos", "cyclic_sin"):
                        self.assertAlmostEqual(result[key], 0, delta=fixture["tolerances"]["hover_cyclic_rad"])

    def test_reverse_flow_is_not_silently_discarded(self):
        with self.assertRaisesRegex(ValueError, "Reverse flow"):
            rotor_performance(30, 25, 1.225, .8, 1300, 2, .06, .012)


class TestTransitionForces(unittest.TestCase):
    def test_predeclared_forces(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/optimization/transition-forces.json").read_text())
        for case in fixture["cases"]:
            result = transition_forces(**{k: case[k] for k in ("mass", "wing_lift", "drag", "acceleration")})
            for key, expected in (("cruise_thrust", "expected_cruise_thrust"),
                                  ("lift_force_x", "expected_lift_x"), ("lift_force_z", "expected_lift_z")):
                self.assertAlmostEqual(result[key], case[expected], delta=fixture["force_tolerance_N"])
            self.assertAlmostEqual(result["force_residual_x"], 0, delta=fixture["force_tolerance_N"])
            self.assertAlmostEqual(result["force_residual_z"], 0, delta=fixture["force_tolerance_N"])

    def test_mission_braking_is_visible_and_constrained(self):
        study = template("lift_cruise")
        study.vehicle.assumptions["transition_tilt_limit"] = 0
        result = evaluate(study)
        self.assertTrue(result.valid, result.errors)
        braking = [r for r in result.mission_history if r["segment"] == "Transition in"]
        self.assertTrue(any(r["lift_force_x"] < 0 for r in braking))
        self.assertLess(result.margins["transition_tilt"], 0)
        self.assertFalse(result.feasible)


class TestDurableStudies(unittest.TestCase):
    def test_independent_rocketpy_vertical_reference(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/optimization/rocketpy-vertical.json").read_text())
        result = evaluate(template("rocket"))
        self.assertTrue(result.valid, result.errors)
        self.assertAlmostEqual(result.metrics["takeoff_mass"], fixture["inputs"]["takeoff_mass_kg"],
                               delta=fixture["tolerances"]["mass_absolute_kg"])
        self.assertAlmostEqual(result.metrics["apogee"], fixture["expected"]["apogee_m"],
                               delta=fixture["tolerances"]["apogee_absolute_m"])

    def test_rocket_both_workflows_preserve_motor_and_performance(self):
        study = template("rocket")
        nominal = evaluate(study)
        p, a = study.vehicle.parameters, study.vehicle.assumptions
        thrust = p["propellant_mass"] * 9.80665 * a["specific_impulse"] / p["burn_time"]
        motor = ComponentDefinition("motor", "rocket_motor", nominal.mass_breakdown["motor"], position=.85*p["body_length"],
                                    properties=dict(thrust_curve=[[0, thrust], [p["burn_time"], thrust]],
                                                    propellant_curve=[[0,p["propellant_mass"]],[p["burn_time"],0]]))
        study.vehicle.components = [motor]
        study.workflow = "hardware"
        before = study.to_dict()
        hardware = evaluate(study)
        self.assertTrue(hardware.valid, hardware.errors)
        for key in ("takeoff_mass", "apogee", "guide_exit_speed", "cg", "landing_speed"):
            self.assertAlmostEqual(hardware.metrics[key], nominal.metrics[key], places=7)
        self.assertEqual(study.to_dict(), before)

    def test_simulated_endurance_constant_electric_load_identity(self):
        study = template()
        study.vehicle.assumptions["resistance"] = 0.
        result = evaluate(study)
        self.assertTrue(result.valid, result.errors)
        # Constant mass, speed and zero internal loss make time exactly proportional
        # to stored energy. The search tolerance is 0.05 seconds.
        expected = 600 * study.vehicle.parameters["storage_margin"]
        self.assertAlmostEqual(result.metrics["endurance"], expected, delta=.1)
        self.assertTrue(result.endurance_history)
        self.assertAlmostEqual(result.endurance_history[-1]["energy"],
                               result.metrics["energy_capacity"] * .8 * .8, delta=20.)

    def test_endurance_preserves_vtol_transition_durations(self):
        study = template("lift_cruise")
        result = evaluate(study)
        self.assertTrue(result.valid, result.errors)
        elapsed = 0.
        durations = {}
        for row in result.endurance_history:
            durations[row["segment"]] = durations.get(row["segment"], 0.) + row["time"] - elapsed
            elapsed = row["time"]
        for segment in study.mission.segments:
            if segment.kind != "cruise":
                self.assertAlmostEqual(durations[segment.name], segment.duration, places=6)
        self.assertGreater(durations["Cruise"], 600)

    def test_uncertainty_keeps_sized_hardware_and_records_samples(self):
        study = template()
        nominal = evaluate(study)
        result = assess_uncertainty(study, {}, {"samples": 3, "inputs": {"cd0": {"lower": .04, "upper": .05}}})
        for row in result.evaluations:
            self.assertTrue(row.valid, row.errors)
            self.assertEqual(row.metrics["energy_capacity"], nominal.metrics["energy_capacity"])
            self.assertEqual(row.metrics["installed_power"], nominal.metrics["installed_power"])
            self.assertGreaterEqual(row.sampled_inputs["cd0"], .04)
            self.assertGreater(row.metrics["energy_required"], nominal.metrics["energy_required"])

    def test_trade_modes_cancel_and_checkpoint(self):
        study = template()
        for mode in ("sweep", "uncertainty", "sensitivity"):
            saved = []
            kwargs = dict(cancel=lambda: len(saved) >= 1, checkpoint=saved.append)
            if mode == "sweep":
                result = sweep(study, {"samples": 5}, **kwargs)
            elif mode == "uncertainty":
                result = assess_uncertainty(study, {}, {"samples": 5, "inputs": {"cd0": {"lower": .03, "upper": .04}}}, **kwargs)
                self.assertEqual(result.summary["completed_samples"], 1)
                self.assertEqual(result.summary["invalid_count"], 0)
            else:
                result = sensitivity(study, **kwargs)
                self.assertEqual(result.summary, {})  # no incomplete derivative
            self.assertEqual(result.status, "cancelled")
            self.assertEqual(len(result.evaluations), 1)
            self.assertEqual(len(saved), 1)

    def test_recovery_preserves_history_and_ignores_incomplete_tail(self):
        study = template()
        result = evaluate(study)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            atomic_json(folder / "request.json", {"study": study.to_dict(), "mode": "optimize"})
            atomic_json(folder / "execution.json", {"model_version": MODEL_VERSION, "input_hash": study.fingerprint()})
            (folder / "evaluations.jsonl").write_bytes((json.dumps(result.to_dict()) + '\n{"design":').encode())
            response = recover(folder)
            self.assertTrue(response["ok"])
            self.assertEqual(response["result"]["status"], "interrupted")
            self.assertEqual(response["result"]["evaluations"], 1)
            self.assertEqual(response["result"]["candidates"][0]["mission_history"], result.mission_history)
            self.assertEqual(recover(folder), response)

    def test_worker_journals_completed_evaluations(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            atomic_json(folder / "request.json", {"study": template().to_dict(), "mode": "sweep", "specification": {"samples": 2}})
            self.assertEqual(execute(folder), 0)
            self.assertEqual(len((folder / "evaluations.jsonl").read_text().splitlines()), 2)

    def test_corruption_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            atomic_json(folder / "request.json", {"study": template().to_dict()})
            atomic_json(folder / "execution.json", {"model_version": MODEL_VERSION, "input_hash": template().fingerprint()})
            (folder / "evaluations.jsonl").write_text("invalid\n")
            with self.assertRaises(json.JSONDecodeError):
                recover(folder)
