"""Physics checks for uavlib against published reference values."""

import math
import unittest

from uavlib import aero, atmosphere, battery, geometry, propulsion, structures, units


class TestAtmosphere(unittest.TestCase):
    # US Standard Atmosphere 1976.
    REFERENCE = {
        0: (288.15, 101325.0, 1.2250),
        5000: (255.65, 54019.9, 0.73612),
        11000: (216.65, 22632.0, 0.36392),
        20000: (216.65, 5474.9, 0.08803),
    }

    def test_matches_standard_tables(self):
        for altitude, (temp, pressure, density) in self.REFERENCE.items():
            air = atmosphere.at(altitude)
            self.assertAlmostEqual(air.temperature, temp, delta=0.1)
            self.assertAlmostEqual(air.pressure, pressure, delta=pressure * 0.001)
            self.assertAlmostEqual(air.density, density, delta=density * 0.002)

    def test_sea_level_viscosity(self):
        self.assertAlmostEqual(atmosphere.viscosity(288.15), 1.789e-5, delta=1e-7)

    def test_speed_of_sound_sea_level(self):
        self.assertAlmostEqual(atmosphere.at(0).sound_speed, 340.3, delta=0.5)

    def test_density_altitude_round_trip(self):
        for altitude in (0, 1000, 3000, 8000):
            back = atmosphere.density_altitude(atmosphere.density(altitude))
            self.assertAlmostEqual(back, altitude, delta=1.0)

    def test_humid_air_is_less_dense(self):
        dry = atmosphere.density_from_conditions(101325, 30, 0.0)
        humid = atmosphere.density_from_conditions(101325, 30, 1.0)
        self.assertLess(humid, dry)

    def test_negative_altitude_clamped(self):
        self.assertAlmostEqual(atmosphere.density(-500), atmosphere.density(0))


class TestUnits(unittest.TestCase):
    def test_bare_number_is_si(self):
        self.assertAlmostEqual(units.parse("0.254", "m"), 0.254)

    def test_imperial_suffixes(self):
        self.assertAlmostEqual(units.parse("10 in", "m"), 0.254, places=6)
        self.assertAlmostEqual(units.parse("3.3 lb", "kg"), 1.49685, places=4)
        self.assertAlmostEqual(units.parse("35 mph", "m/s"), 15.6464, places=3)
        self.assertAlmostEqual(units.parse("1200 g", "kg"), 1.2, places=6)

    def test_propeller_size_notation(self):
        self.assertAlmostEqual(units.parse("10x4.7", "m"), 0.254, places=6)

    def test_wrong_dimension_rejected(self):
        with self.assertRaises(units.UnitError):
            units.parse("5 kg", "m")

    def test_fraction_accepts_percent_and_decimal(self):
        for text in ("80%", "80", "0.8"):
            self.assertAlmostEqual(units.fraction({"x": text}, "x"), 0.8)

    def test_positive_rejects_zero(self):
        with self.assertRaises(units.UnitError):
            units.positive({"x": "0"}, "x", "m", "Span")

    def test_blank_returns_default(self):
        self.assertEqual(units.optional({"x": ""}, "x", "m", 1.5), 1.5)


class TestAero(unittest.TestCase):
    def test_flap_effectiveness_never_exceeds_one(self):
        # The defect this replaced returned 1.218 at cf/c = 0.25.
        for cf in (0.05, 0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 1.0):
            self.assertLessEqual(aero.flap_effectiveness(cf, viscous=False), 1.0)
            self.assertGreater(aero.flap_effectiveness(cf), 0.0)

    def test_flap_effectiveness_reference_values(self):
        self.assertAlmostEqual(aero.flap_effectiveness(0.25, viscous=False), 0.609,
                               places=3)
        self.assertAlmostEqual(aero.flap_effectiveness(0.10, viscous=False), 0.396,
                               places=3)
        # A full-chord "flap" is just the whole surface pivoting: tau -> 1.
        self.assertAlmostEqual(aero.flap_effectiveness(1.0, viscous=False), 1.0,
                               places=6)

    def test_flap_effectiveness_monotonic(self):
        values = [aero.flap_effectiveness(c) for c in (0.1, 0.2, 0.3, 0.4, 0.5)]
        self.assertEqual(values, sorted(values))

    def test_lift_slope_below_two_pi(self):
        for ar in (4, 8, 16):
            self.assertLess(aero.lift_curve_slope_3d(ar), 2 * math.pi)
        # Higher aspect ratio approaches the 2D value.
        self.assertLess(aero.lift_curve_slope_3d(6), aero.lift_curve_slope_3d(12))

    def test_stall_speed_scales_with_root_load_factor(self):
        base = aero.stall_speed(1.5, 0.3, 1.2)
        self.assertAlmostEqual(aero.stall_speed(1.5, 0.3, 1.2, load_factor=4),
                               base * 2.0, places=6)

    def test_min_power_speed_is_below_min_drag_speed(self):
        k = aero.induced_drag_factor(8, 0.8)
        v_drag = aero.speed_min_drag(1.5, 0.3, 0.03, k)
        v_power = aero.speed_min_power(1.5, 0.3, 0.03, k)
        self.assertAlmostEqual(v_power / v_drag, 3 ** -0.25, places=6)

    def test_ld_max_occurs_where_drags_are_equal(self):
        cd0, k = 0.03, 0.05
        ld, cl = aero.ld_max(cd0, k)
        self.assertAlmostEqual(k * cl ** 2, cd0, places=9)
        self.assertAlmostEqual(ld, cl / aero.drag_polar(cl, cd0, k), places=9)

    def test_static_margin_sign(self):
        # CG ahead of the neutral point is stable, giving a positive margin.
        self.assertGreater(aero.static_margin(0.10, 0.15, 0.2), 0)
        self.assertLess(aero.static_margin(0.20, 0.15, 0.2), 0)

    def test_roll_damping_is_negative(self):
        self.assertLess(aero.roll_damping(5.0, 8, 1.0), 0)


class TestPropulsion(unittest.TestCase):
    def test_real_hover_power_exceeds_ideal(self):
        thrust, diameter = 14.7, 0.254
        ideal = propulsion.ideal_hover_power(thrust, diameter, count=4)
        real = propulsion.hover_power(thrust, diameter, 0.65, count=4)
        self.assertGreater(real, ideal)
        self.assertAlmostEqual(real * 0.65, ideal, places=6)

    def test_hover_power_round_trip(self):
        thrust = 14.7
        power = propulsion.hover_power(thrust, 0.254, 0.65, count=4)
        back = propulsion.thrust_from_power(power, 0.254, 0.65, count=4)
        self.assertAlmostEqual(back, thrust, places=4)

    def test_larger_disk_needs_less_power(self):
        small = propulsion.hover_power(14.7, 0.20, count=4)
        large = propulsion.hover_power(14.7, 0.35, count=4)
        self.assertLess(large, small)

    def test_static_thrust_matches_published_prop_data(self):
        # APC 10x4.7 at 8000 rpm is about 10 N and 130 W.
        thrust = propulsion.static_thrust(0.254, 0.1194, 8000)
        power = propulsion.static_shaft_power(0.254, 0.1194, 8000)
        self.assertAlmostEqual(thrust, 10.0, delta=1.5)
        self.assertAlmostEqual(power, 130.0, delta=20.0)

    def test_thrust_scales_with_rpm_squared(self):
        low = propulsion.static_thrust(0.254, 0.1194, 4000)
        high = propulsion.static_thrust(0.254, 0.1194, 8000)
        self.assertAlmostEqual(high / low, 4.0, places=4)

    def test_hover_efficiency_in_expected_band(self):
        thrust = 1.5 * 9.80665
        shaft = propulsion.hover_power(thrust, 0.254, 0.65, count=4)
        electrical = propulsion.electrical_power(shaft)
        self.assertTrue(7.0 < propulsion.hover_efficiency(thrust, electrical) < 13.0)

    def test_best_range_speed_exceeds_best_endurance(self):
        endurance, best_range = propulsion.best_cruise_speed(1.5, 0.254, 4, 0.010)
        self.assertGreater(best_range, endurance)

    def test_forward_flight_induced_power_falls_with_speed(self):
        hover = propulsion.forward_flight_power(1.5, 0.0, 0.254, 4, 0.01)
        fast = propulsion.forward_flight_power(1.5, 12.0, 0.254, 4, 0.01)
        self.assertLess(fast["induced"], hover["induced"])

    def test_efficiency_chain_multiplies(self):
        self.assertAlmostEqual(
            propulsion.drive_chain_efficiency(0.7, 0.8, 0.95, 0.98),
            0.7 * 0.8 * 0.95 * 0.98, places=9)


class TestGeometry(unittest.TestCase):
    def test_planform_area_is_consistent(self):
        wing = geometry.wing_from_area_ar(0.30, 8, 0.6)
        area = (wing.root_chord + wing.tip_chord) / 2.0 * wing.span
        self.assertAlmostEqual(area, 0.30, places=6)
        self.assertAlmostEqual(wing.span ** 2 / wing.area, 8, places=6)

    def test_rectangular_wing_mac_equals_chord(self):
        wing = geometry.wing_from_area_ar(0.30, 8, 1.0)
        self.assertAlmostEqual(wing.mac, wing.root_chord, places=6)
        self.assertAlmostEqual(wing.mac, wing.mean_chord, places=6)

    def test_mac_lies_between_tip_and_root_chord(self):
        wing = geometry.wing_from_area_ar(0.4, 7, 0.5)
        self.assertLess(wing.mac, wing.root_chord)
        self.assertGreater(wing.mac, wing.tip_chord)

    def test_coaxial_layouts_have_fewer_arms_than_motors(self):
        for name in ("Y6", "X8 (over-under)"):
            frame = geometry.layout(name)
            self.assertLess(frame.arms, frame.motors)
            self.assertTrue(frame.coaxial)

    def test_x8_frame_is_smaller_than_octocopter(self):
        # The whole point of over-under: octocopter thrust on a quad frame.
        x8 = geometry.arm_length_for_clearance(0.254, geometry.layout("X8 (over-under)").arms)
        octo = geometry.arm_length_for_clearance(0.254, geometry.layout("Octocopter").arms)
        self.assertLess(x8, octo)

    def test_coaxial_thrust_penalised(self):
        x8 = geometry.effective_thrust(10.0, geometry.layout("X8 (over-under)"))
        octo = geometry.effective_thrust(10.0, geometry.layout("Octocopter"))
        self.assertLess(x8, octo)
        self.assertAlmostEqual(x8, 80.0 * (1 - geometry.COAXIAL_PENALTY), places=6)

    def test_coaxial_disk_count_follows_arms(self):
        # A coaxial pair shares one rotor disk, so an X8 has four, not eight.
        self.assertEqual(geometry.disk_count(geometry.layout("X8 (over-under)")), 4)
        self.assertEqual(geometry.disk_count(geometry.layout("Y6")), 3)
        self.assertEqual(geometry.disk_count(geometry.layout("Octocopter")), 8)
        self.assertEqual(geometry.disk_count(geometry.layout("Quadcopter X")), 4)

    def test_coaxial_hovers_worse_than_flat_frame(self):
        """An X8 must need more power than a quad of the same mass and rotor.

        Counting eight independent disks instead of four made the X8 look more
        efficient than the quad, which inverts the real trade-off.
        """
        weight, diameter = 14.71, 0.254
        quad = geometry.layout("Quadcopter X")
        x8 = geometry.layout("X8 (over-under)")

        quad_power = propulsion.hover_power(weight, diameter, 0.65, 0.0,
                                            geometry.disk_count(quad))
        x8_power = propulsion.hover_power(weight, diameter, 0.65, 0.0,
                                          geometry.disk_count(x8))
        x8_power /= propulsion.COAXIAL_EFFICIENCY
        self.assertGreater(x8_power, quad_power)

    def test_plus_layout_has_arm_on_nose(self):
        frame = geometry.layout("Quadcopter +", 1.0)
        angles = sorted(round(math.degrees(math.atan2(y, x)) % 360) for x, y in frame.positions)
        self.assertEqual(angles, [0, 90, 180, 270])

    def test_x_layout_straddles_nose(self):
        frame = geometry.layout("Quadcopter X", 1.0)
        angles = sorted(round(math.degrees(math.atan2(y, x)) % 360) for x, y in frame.positions)
        self.assertEqual(angles, [45, 135, 225, 315])

    def test_tip_clearance_matches_spacing_factor(self):
        diameter = 0.254
        arm = geometry.arm_length_for_clearance(diameter, 4, 1.2)
        gap = geometry.tip_clearance(arm, 4, diameter)
        self.assertAlmostEqual(gap, 0.2 * diameter, places=6)

    def test_mixing_covers_every_motor(self):
        for name, frame in ((n, geometry.layout(n)) for n in geometry.LAYOUTS):
            self.assertEqual(len(geometry.mixing_matrix(frame)), frame.motors,
                             f"{name} mixing row count")

    def test_tricopter_yaw_comes_from_servo(self):
        rows = geometry.mixing_matrix(geometry.layout("Tricopter"))
        self.assertTrue(all(row["yaw"] == 0.0 for row in rows))

    def test_roll_demand_is_antisymmetric(self):
        frame = geometry.layout("Quadcopter X", 0.25)
        rows = geometry.motor_demands(frame, 4.0, roll=0.3)
        self.assertAlmostEqual(sum(r["thrust"] for r in rows), 16.0, places=6)

    def test_unknown_layout_rejected(self):
        with self.assertRaises(ValueError):
            geometry.layout("Nonacopter")


class TestStructures(unittest.TestCase):
    def test_tube_beats_solid_rod_per_unit_mass(self):
        tube = structures.tube_properties(0.010, 0.001)
        rod = structures.solid_rod_properties(0.010)
        self.assertLess(tube["I"], rod["I"])
        # But far more second moment for the material used.
        self.assertGreater(tube["I"] / tube["area"], rod["I"] / rod["area"])

    def test_elliptical_root_moment_below_uniform(self):
        elliptical = structures.elliptical_lift_root_moment(30, 1.5)
        uniform = structures.uniform_lift_root_moment(30, 1.5)
        self.assertLess(elliptical, uniform)

    def test_cantilever_deflection_cubic_in_length(self):
        material = structures.MATERIALS["Carbon fibre tube (pultruded)"]
        section = structures.tube_properties(0.010, 0.001)
        short = structures.cantilever_deflection(10, 0.25, material["E"], section["I"])
        long = structures.cantilever_deflection(10, 0.50, material["E"], section["I"])
        self.assertAlmostEqual(long / short, 8.0, places=6)

    def test_margin_of_safety_sign(self):
        self.assertGreater(structures.margin_of_safety(100e6, 600e6), 0)
        self.assertLess(structures.margin_of_safety(700e6, 600e6), 0)

    def test_required_section_modulus_includes_safety_factor(self):
        base = structures.required_section_modulus(10, 100e6, 1.0)
        with_margin = structures.required_section_modulus(10, 100e6, 1.5)
        self.assertAlmostEqual(with_margin / base, 1.5, places=9)


class TestBattery(unittest.TestCase):
    def test_pack_resistance_matches_measured_packs(self):
        # A 4S 5000 mAh LiPo measures around 16 milliohm.
        resistance = battery.internal_resistance(4, 5.0, "LiPo")
        self.assertAlmostEqual(resistance * 1000, 16.0, delta=4.0)

    def test_sag_grows_with_current(self):
        low = battery.voltage_under_load(4, 5.0, 20)
        high = battery.voltage_under_load(4, 5.0, 80)
        self.assertGreater(high["sag"], low["sag"])
        self.assertLess(high["loaded"], low["loaded"])

    def test_small_pack_sags_more(self):
        big = battery.voltage_under_load(4, 5.0, 60)
        small = battery.voltage_under_load(4, 1.3, 60)
        self.assertGreater(small["sag"], big["sag"])

    def test_parallel_strings_reduce_resistance(self):
        single = battery.internal_resistance(4, 5.0, "LiPo", parallel=1)
        double = battery.internal_resistance(4, 10.0, "LiPo", parallel=2)
        self.assertLess(double, single)

    def test_wire_selection_picks_smallest_adequate(self):
        # Must not return the thickest gauge for a small current.
        self.assertEqual(battery.recommend_wire(5)["awg"], 22)
        self.assertEqual(battery.recommend_wire(30)["awg"], 12)
        chosen = battery.recommend_wire(60)
        self.assertGreaterEqual(chosen["rated_a"], 60 * 1.25)

    def test_wire_warns_when_beyond_table(self):
        self.assertIn("warning", battery.recommend_wire(400))

    def test_usable_energy_respects_depth_of_discharge(self):
        self.assertAlmostEqual(battery.usable_energy(14.8, 5.0, 0.8),
                               14.8 * 5.0 * 0.8, places=9)

    def test_c_rate(self):
        self.assertAlmostEqual(battery.c_rate(50, 5.0), 10.0, places=9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
