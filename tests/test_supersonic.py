"""Supersonic physics and the supersonic jet design family, against references.

Exact gas dynamics are pinned to NACA Report 1135 values; theory checks use
closed-form results (Sears-Haack, Ackeret, Bonney, slender delta wings); the
sonic boom is compared with Concorde's measured overpressure.
"""

import math
import os
import sys
import unittest
from copy import deepcopy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from uavlib import (aerothermal, airbreathing, area_rule, compressible, jet_performance,  # noqa: E402
                    jet_weights, sonic_boom, structures, supersonic, units)
from uavlib.optimization import (ComponentDefinition, OperatingScenario, assess_uncertainty,  # noqa: E402
                                 evaluate, optimize, template)
from uavlib.optimization.physics import interpolate_grid  # noqa: E402


class TestCompressible(unittest.TestCase):
    """NACA Report 1135, gamma = 1.4."""

    def test_isentropic_mach_2(self):
        values = compressible.isentropic(2.0)
        self.assertAlmostEqual(values["p/p0"], 0.12780, places=5)
        self.assertAlmostEqual(values["T/T0"], 0.55556, places=5)
        self.assertAlmostEqual(values["A/A*"], 1.68750, places=5)
        self.assertAlmostEqual(values["mu_deg"], 30.0, places=6)
        self.assertAlmostEqual(values["nu_deg"], 26.380, places=3)

    def test_normal_shock_mach_2(self):
        shock = compressible.normal_shock(2.0)
        self.assertAlmostEqual(shock["M2"], 0.57735, places=5)
        self.assertAlmostEqual(shock["p2/p1"], 4.5, places=6)
        self.assertAlmostEqual(shock["T2/T1"], 1.6875, places=4)
        self.assertAlmostEqual(shock["p02/p01"], 0.72087, places=5)

    def test_oblique_shock_mach_2_ten_degrees(self):
        shock = compressible.oblique_shock(2.0, math.radians(10))
        self.assertAlmostEqual(shock["beta_deg"], 39.31, places=2)
        self.assertAlmostEqual(shock["M2"], 1.6405, places=3)
        self.assertAlmostEqual(shock["p2/p1"], 1.7066, places=3)
        self.assertAlmostEqual(math.degrees(compressible.max_deflection(2.0)), 22.97, places=2)
        with self.assertRaises(ValueError):
            compressible.oblique_shock(2.0, math.radians(25))   # detached

    def test_prandtl_meyer_and_area_inverse(self):
        self.assertAlmostEqual(math.degrees(compressible.prandtl_meyer(1.5)), 11.905, places=3)
        self.assertAlmostEqual(math.degrees(compressible.prandtl_meyer(3.0)), 49.757, places=3)
        self.assertAlmostEqual(compressible.mach_from_area_ratio(1.6875), 2.0, places=6)
        self.assertAlmostEqual(compressible.mach_from_prandtl_meyer(compressible.prandtl_meyer(1.7)), 1.7, places=6)

    def test_cone_flow_is_weaker_than_wedge(self):
        for angle in (5, 10, 20):
            cone = compressible.cone_flow(2.0, math.radians(angle))
            wedge = compressible.oblique_shock(2.0, math.radians(angle))
            self.assertLess(cone["beta_deg"], wedge["beta_deg"])
            self.assertGreater(cone["beta_deg"], 30.0)            # above the Mach angle
        self.assertAlmostEqual(compressible.cone_flow(2.0, math.radians(20))["beta_deg"], 37.8, delta=0.3)


class TestAreaRule(unittest.TestCase):
    def test_sears_haack_body_reproduces_analytic_drag(self):
        length, area = 4.0, 0.05
        xs = [length * i / 200 for i in range(201)]
        areas = [area_rule.sears_haack_area(x, length, area) for x in xs]
        self.assertAlmostEqual(area_rule.wave_drag_dq(xs, areas) / area_rule.sears_haack_dq(area, length),
                               1.0, delta=0.005)
        coefficients = area_rule.fourier_coefficients(xs, areas, 4)
        self.assertAlmostEqual(coefficients[1], 3 * area / length, delta=1e-5)  # single n=2 term

    def test_volume_identity(self):
        self.assertAlmostEqual(area_rule.sears_haack_volume(3.0, 0.1), 3 * math.pi * 3.0 * 0.1 / 16)


class TestSupersonicAero(unittest.TestCase):
    def test_linear_theory_matches_shock_expansion(self):
        for alpha in (0, 2, 4):
            linear = supersonic.airfoil_linear(2.0, alpha, 0.05, "diamond")
            exact = supersonic.diamond_shock_expansion(2.0, alpha, 0.05)
            self.assertAlmostEqual(linear["cd"], exact["cd"], delta=0.03 * exact["cd"])
            if alpha:
                self.assertAlmostEqual(linear["cl"], exact["cl"], delta=0.03 * exact["cl"])

    def test_wing_lift_slope_limits(self):
        # Rectangular wing, supersonic edges: Bonney 4/beta (1 - 1/(2 A beta)).
        beta = math.sqrt(3.0)
        self.assertAlmostEqual(supersonic.wing_lift_slope(2.0, 3.0, 0.0, 1.0),
                               4 / beta * (1 - 1 / (2 * 3 * beta)), places=6)
        # Delta wing with a sonic leading edge: CL_alpha = A (= 4/beta).
        aspect = 4 / math.tan(math.radians(60))
        self.assertAlmostEqual(supersonic.wing_lift_slope(2.0, aspect, 60.0, 0.0), aspect, places=3)
        # Slender delta (Mach-cone parameter -> 0) tends to Jones' pi A / 2.
        self.assertAlmostEqual(supersonic._lift_slope_supersonic(1.2, 1.0, 89.0, 0.0),
                               math.pi / 2, delta=0.002)

    def test_mach_ceiling_enforced(self):
        with self.assertRaises(ValueError):
            supersonic.wing_lift_slope(2.1, 3.0)

    def test_drag_rises_through_mach_one(self):
        config = supersonic.Configuration(wing_area=1.2)
        subsonic = config.cd0(0.8, 11000)["total"]
        transonic = config.cd0(1.05, 11000)["total"]
        self.assertGreater(transonic, 1.3 * subsonic)
        self.assertEqual(config.cd0(0.5, 11000)["wave"], 0.0)

    def test_korn_drag_divergence(self):
        self.assertAlmostEqual(supersonic.drag_divergence_mach(0.12, 0.4, 0.0), 0.87 - 0.12 - 0.04)


class TestPropulsion(unittest.TestCase):
    def test_inlets(self):
        self.assertAlmostEqual(airbreathing.pitot_recovery(2.0), 0.72087, places=5)
        self.assertAlmostEqual(airbreathing.mil_spec_recovery(2.0), 0.925, places=6)
        one, two = airbreathing.optimum_ramps(2.0, 1), airbreathing.optimum_ramps(2.0, 2)
        self.assertGreater(one["recovery"], airbreathing.pitot_recovery(2.0))
        self.assertGreater(two["recovery"], one["recovery"])
        self.assertAlmostEqual(one["recovery"], 0.90, delta=0.01)

    def test_turbojet_scales_and_is_consistent(self):
        small = airbreathing.Turbojet(sls_thrust=400, pressure_ratio=3.8, tt4_max=1100)
        big = airbreathing.Turbojet(sls_thrust=800, pressure_ratio=3.8, tt4_max=1100)
        self.assertAlmostEqual(small.point(0, 0)["thrust"], 400, places=6)
        a, b = small.max_thrust(1.4, 9000), big.max_thrust(1.4, 9000)
        self.assertAlmostEqual(b["thrust"] / a["thrust"], 2.0, places=9)
        self.assertAlmostEqual(b["tsfc"], a["tsfc"], places=12)
        # Model-turbine class: about 0.5 kN s/kg specific thrust, 35-55 mg/(N s).
        sls = small.point(0, 0)
        self.assertTrue(450 < sls["specific_thrust"] < 650)
        self.assertTrue(35e-6 < sls["tsfc"] < 55e-6)

    def test_afterburner_and_part_power(self):
        engine = airbreathing.Turbojet(sls_thrust=1000, afterburner=True)
        dry, wet = engine.max_thrust(1.5, 11000, False), engine.max_thrust(1.5, 11000, True)
        self.assertGreater(wet["thrust"], 1.4 * dry["thrust"])
        self.assertGreater(wet["tsfc"], dry["tsfc"])
        part = engine.thrust_for(0.7 * dry["thrust"], 1.5, 11000)
        self.assertAlmostEqual(part["thrust"], 0.7 * dry["thrust"], places=6)
        self.assertLess(part["fuel_flow"], dry["fuel_flow"])
        self.assertIsNone(engine.thrust_for(2 * wet["thrust"], 1.5, 11000))


class TestEnvironmentAndStructure(unittest.TestCase):
    def test_concorde_boom(self):
        # Concorde at Mach 2 and ~16.5 km produced about 93 Pa (1.94 psf).
        concorde = supersonic.Configuration(
            wing_area=358, aspect_ratio=1.55, le_sweep_deg=60, taper=0.05, thickness_ratio=0.03,
            body_length=61.7, body_diameter=2.9, nose_fineness=5, vtail_area=34, tail_arm=20,
            inlet_capture_area=2.8, wing_position=0.6)
        boom = sonic_boom.aircraft_boom(concorde, 1.8e6, 2.0, 16500)
        self.assertAlmostEqual(boom["overpressure"], 93.0, delta=0.2 * 93.0)

    def test_boom_cutoff_and_altitude_scaling(self):
        config = supersonic.Configuration(wing_area=1.2)
        self.assertFalse(sonic_boom.aircraft_boom(config, 1000, 1.1, 11000)["reaches_ground"])
        xs = [i * 0.05 for i in range(81)]
        areas = [area_rule.sears_haack_area(x, 4.0, 0.05) for x in xs]
        low = sonic_boom.ground_signature(xs, areas, 1.6, 12000)
        high = sonic_boom.ground_signature(xs, areas, 1.6, 15000)
        expected = (15000 / 12000) ** -0.75 * math.sqrt(
            atmosphere_pressure(15000) / atmosphere_pressure(12000))
        self.assertAlmostEqual(high["overpressure"] / low["overpressure"], expected, places=6)

    def test_skin_temperature(self):
        t = aerothermal.skin_temperature(2.0, 11000)
        self.assertAlmostEqual(t["stagnation"], 216.65 * 1.8, places=3)
        self.assertAlmostEqual(t["recovery"], 216.65 * (1 + 0.2 * 4 * 0.71 ** (1 / 3)), places=3)
        self.assertTrue(216.65 < t["equilibrium"] <= t["recovery"])

    def test_panel_flutter_minimum_thickness_is_critical(self):
        result = structures.panel_flutter(1.6, 40000, 0.15, 0.001, 50e9)
        edge = structures.panel_flutter(1.6, 40000, 0.15, result["minimum_thickness"], 50e9)
        self.assertAlmostEqual(edge["margin"], 0.0, places=9)

    def test_weights_close(self):
        config = supersonic.Configuration(wing_area=1.2)
        mass, breakdown, _ = jet_weights.close(config, jet_weights.Technology(), 1500, True, 10, 40)
        self.assertAlmostEqual(mass, sum(breakdown.values()), delta=1e-4)

    def test_constraint_takeoff_scales_with_wing_loading(self):
        engine = airbreathing.Turbojet(sls_thrust=1000)
        low = jet_performance.takeoff_thrust_loading(500, engine, 1.0, 150)
        high = jet_performance.takeoff_thrust_loading(1000, engine, 1.0, 150)
        self.assertGreater(high, low)


def atmosphere_pressure(altitude):
    from uavlib import atmosphere
    return atmosphere.at(altitude).pressure


class TestUnitsAndTables(unittest.TestCase):
    def test_temperature_and_tsfc_units(self):
        self.assertAlmostEqual(units.parse("100 C", "K"), 373.15)
        self.assertAlmostEqual(units.parse("212 F", "K"), 373.15)
        self.assertAlmostEqual(units.to(373.15, "C"), 100.0)
        self.assertAlmostEqual(units.parse("1 lb/lbf/h", "kg/(N.s)"), 2.832545e-5)

    def test_grid_interpolation_is_bilinear_and_strict(self):
        rows = [{"mach": m, "altitude": h, "v": 2 * m + 3 * h + m * h} for m in (0, 1) for h in (0, 2)]
        self.assertAlmostEqual(interpolate_grid(rows, ("mach", 0.25), ("altitude", 1.5), "v"),
                               2 * 0.25 + 3 * 1.5 + 0.25 * 1.5)
        with self.assertRaises(ValueError):
            interpolate_grid(rows, ("mach", 1.1), ("altitude", 1), "v")


class TestSupersonicFamily(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.study = template("supersonic")
        cls.base = evaluate(cls.study)

    def test_template_evaluates_and_converges(self):
        self.assertTrue(self.base.valid, self.base.errors)
        self.assertTrue(self.base.converged)
        m = self.base.metrics
        self.assertAlmostEqual(m["takeoff_mass"], sum(self.base.mass_breakdown.values()), delta=1e-6)
        self.assertGreater(m["installed_thrust"], 0)
        self.assertLessEqual(m["max_mach"], 2.0)
        # Thrust is sized with a factor, so the margin (available - required) / available
        # is at least 1 - 1/factor at the most demanding point.
        factor = self.study.vehicle.parameters["thrust_margin"]
        self.assertGreaterEqual(self.base.margins["thrust"], 1 - 1 / factor - 1e-3)

    def test_requirements_to_hardware_forward_equivalence(self):
        hardware = deepcopy(self.study)
        hardware.workflow, hardware.variables = "hardware", []
        hardware.objectives = template("supersonic", "hardware").objectives
        b = self.base
        hardware.vehicle.components = [
            ComponentDefinition("engine", "jet_engine", b.mass_breakdown["engine"], 1, 0.,
                                {"sls_thrust": b.metrics["installed_thrust"], "afterburner": True}),
            ComponentDefinition("tank", "tank", b.mass_breakdown["fuel system"], 1, 0.,
                                {"fuel_mass": b.metrics["fuel_capacity"]})]
        fixed = evaluate(hardware)
        self.assertTrue(fixed.valid, fixed.errors)
        for key in ("takeoff_mass", "fuel_used", "range", "transonic_excess_power"):
            self.assertAlmostEqual(fixed.metrics[key] / b.metrics[key], 1.0, delta=1e-4, msg=key)

    def test_hardware_needs_an_engine(self):
        hardware = deepcopy(self.study)
        hardware.workflow, hardware.variables = "hardware", []
        result = evaluate(hardware)
        self.assertFalse(result.valid)
        self.assertIn("jet_engine", result.errors[0])

    def test_robust_scenario_and_uncertainty_stay_valid(self):
        robust = deepcopy(self.study)
        robust.robust = True
        robust.scenarios = [OperatingScenario("Fast", 1000., 1.1, 2.0)]
        self.assertTrue(evaluate(robust).valid)
        spec = {"samples": 4, "seed": 1,
                "inputs": {"e_wd": {"distribution": "uniform", "lower": 1.5, "upper": 2.6}}}
        self.assertEqual(assess_uncertainty(self.study, {}, spec).summary["invalid_count"], 0)

    def test_rejects_wrong_propulsion_and_segments(self):
        with self.assertRaises(ValueError):
            template("fixed_wing", propulsion="turbojet")
        bad = deepcopy(self.study)
        bad.mission.segments[0].kind = "hover"
        self.assertFalse(evaluate(bad).valid)

    def test_short_optimization_runs(self):
        study = deepcopy(self.study)
        study.max_evaluations = 40
        result = optimize(study)
        self.assertEqual(result.evaluations, 40)
        self.assertIn(result.status, ("completed", "budget_exhausted", "solver_stopped",
                                      "no_feasible_design_found"))


if __name__ == "__main__":
    unittest.main()
