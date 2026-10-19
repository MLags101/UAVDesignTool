"""Measured UIUC propeller points and independently specified circuit identities."""
import json
import math
from pathlib import Path
import unittest
import tempfile
from copy import deepcopy
from uavlib.optimization.propulsion import propeller_point, electric_drive, motor_operating_point
from uavlib.optimization import template, evaluate, ComponentDefinition
from uavlib.optimization.data import read_propeller_csv


class TestMappedDrive(unittest.TestCase):
    def test_csv_preserves_rpm_slices_and_rejects_reordered_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.csv"
            path.write_text("rpm,J,CT,CP\n5000,0,.1,.05\n5000,.5,.08,.06\n6000,0,.11,.06\n6000,.5,.09,.07\n")
            data = read_propeller_csv(path)
            self.assertEqual(data[1]["rpm"], 6000)
            self.assertEqual(data[0]["points"][1], [.5,.08,.06])
            path.write_text("rpm,J,CT,CP\n5000,.5,.1,.05\n5000,0,.08,.06\n")
            with self.assertRaises(ValueError):
                read_propeller_csv(path)
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent / "fixtures/optimization/propulsion-reference.json").read_text())
        self.prop = {k: self.fixture[k] for k in ("diameter", "performance_map")}
        self.motor = dict(kv_rpm_per_volt=1000., resistance=.05, no_load_current=1., max_current=50., max_power=500., max_rpm=7000.)
        self.controller = dict(efficiency=.97, max_motor_current=50., max_current=50.)

    def test_measured_point_and_dimensional_relations(self):
        c = self.fixture["check"]
        n, diameter, rho = c["rpm"] / 60, self.prop["diameter"], c["rho"]
        speed = c["J"] * n * diameter
        result = propeller_point(self.prop, c["rpm"], speed, rho)
        self.assertAlmostEqual(result["thrust"], c["CT"] * rho * n*n * diameter**4, places=10)
        self.assertAlmostEqual(result["shaft_power"], c["CP"] * rho * n**3 * diameter**5, places=10)
        self.assertAlmostEqual(result["propeller_efficiency"], c["eta_published"], delta=.001)
        drive = electric_drive(result["thrust"], speed, rho, self.prop, self.motor, self.controller)
        self.assertAlmostEqual(drive["rpm"], c["rpm"], delta=.0001)
        kt = 60 / (2 * math.pi * self.motor["kv_rpm_per_volt"])
        self.assertAlmostEqual((drive["motor_current"] - 1.) * kt, result["torque"], places=10)
        copper = drive["motor_current"]**2 * self.motor["resistance"]
        rotational = c["rpm"] / self.motor["kv_rpm_per_volt"] * self.motor["no_load_current"]
        self.assertAlmostEqual(drive["bus_power"] * .97, result["shaft_power"] + copper + rotational, places=8)

    def test_invalid_domains_and_ratings(self):
        with self.assertRaises(ValueError):
            propeller_point(self.prop, 7000, 10, 1.225)
        with self.assertRaises(ValueError):
            electric_drive(1000, 8, 1.225, self.prop, self.motor, self.controller)
        self.motor["max_current"] = .1
        reference = propeller_point(self.prop, 5500, 8, 1.225)
        drive = electric_drive(reference["thrust"], 8, 1.225, self.prop, self.motor, self.controller)
        self.assertLess(drive["motor_current_margin"], 0)

    def test_rotor_motor_rpm_limit_is_an_explicit_margin(self):
        result = motor_operating_point(100., 8000., self.motor, self.controller)
        self.assertLess(result["motor_rpm_margin"], 0.)
        self.assertGreater(result["bus_power"], 100.)

    def test_multirotor_measured_hover_path_and_edgewise_domain(self):
        from examples.optimization_workflows import locked_example
        study = template("multirotor")
        fixed = locked_example(study, evaluate(study))
        for part in fixed.vehicle.components:
            if part.kind == "motor":
                part.quantity, part.mass = 4, part.mass / 4
                part.properties = deepcopy(self.motor)
            elif part.kind == "controller":
                part.quantity = 4
                part.properties = deepcopy(self.controller)
            elif part.kind == "propeller":
                part.properties = dict(diameter=.5, performance_map=[dict(rpm=rpm, points=[[0,.1,.06],[1,.05,.08]]) for rpm in (100,15000)])
        result = evaluate(fixed)
        self.assertTrue(result.valid, result.errors)
        self.assertGreater(result.mission_history[0]["drive_rpm"], 0)
        fixed.mission.segments[0].speed = 5.
        result = evaluate(fixed)
        self.assertFalse(result.valid)
        self.assertIn("edgewise", str(result.errors))

    def test_hardware_mission_uses_drive_and_preserves_parts(self):
        # Wide synthetic map isolates integration from the limited measured test envelope.
        study = template(workflow="hardware")
        study.variables = []
        prop = dict(diameter=.4, performance_map=[dict(rpm=rpm, points=[[0,.1,.06],[1,.05,.08]]) for rpm in (500,15000)])
        study.vehicle.components = [
            ComponentDefinition("motor", "motor", .15, properties=self.motor),
            ComponentDefinition("prop", "propeller", .05, properties=prop),
            ComponentDefinition("esc", "controller", .05, properties=self.controller),
            ComponentDefinition("battery", "battery", .6, properties=dict(energy=400000., voltage=22.2,
                                resistance=.03, min_voltage=18., max_current=100.))]
        before = deepcopy(study.to_dict())
        result = evaluate(study)
        self.assertTrue(result.valid, result.errors)
        self.assertIn("drive_voltage_margin", result.margins)
        self.assertGreater(result.mission_history[0]["drive_rpm"], 0)
        self.assertEqual(before, study.to_dict())


if __name__ == "__main__":
    unittest.main()
