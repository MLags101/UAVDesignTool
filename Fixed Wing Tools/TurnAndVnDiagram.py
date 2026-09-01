"""
Turn Performance and V-n Diagram

Two related questions answered from the same data: how tightly can it turn, and
how fast can it be flown before control inputs or gusts overstress it.

The V-n diagram's defining feature is the manoeuvre (corner) speed, where the
stall boundary meets the structural limit. Below it the wing stalls before the
structure is threatened; above it, full elevator can break the aircraft.
"""

import math

from uavlib import aero, atmosphere, plotting, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Turn Performance & V-n Diagram",
    "category": "Fixed Wing / Performance",
    "description": (
        "Turn radius, rate and load factor against bank angle, plus the "
        "manoeuvre and gust envelope. Identifies the corner speed and the "
        "sustained turn limited by available power."
    ),
    "inputs": [
        {"key": "mass", "label": "Total Mass", "unit": "kg", "type": "number"},
        {"key": "wing_area", "label": "Wing Area (S)", "unit": "m^2",
         "type": "number"},
        {"key": "span", "label": "Wing Span (b)", "unit": "m", "type": "number"},
        {"key": "cl_max", "label": "Max Lift Coefficient", "type": "number",
         "default": "1.2"},
        {"key": "cd0", "label": "Parasite Drag (CD0)", "type": "number",
         "default": "0.035"},
        {"key": "limit_load", "label": "Positive Limit Load", "unit": "g",
         "type": "number", "default": "6.0",
         "help": "3.8 for a trainer, 6 for sport, 9-12 for aerobatic."},
        {"key": "negative_limit", "label": "Negative Limit Load", "unit": "g",
         "type": "number", "default": "-3.0"},
        {"key": "v_max", "label": "Never-Exceed Speed (Vne)", "unit": "m/s",
         "type": "number", "help": "Blank estimates it as 1.4x cruise."},
        {"key": "cruise_speed", "label": "Cruise Speed", "unit": "m/s",
         "type": "number"},
        {"key": "available_power", "label": "Available Power", "unit": "W",
         "type": "number", "help": "Optional: gives the sustained turn limit."},
        {"key": "prop_efficiency", "label": "Propeller Efficiency",
         "type": "number", "default": "0.65"},
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number",
         "default": "0"},
        {"key": "gust_velocity", "label": "Gust Velocity", "unit": "m/s",
         "type": "number", "default": "7.5",
         "help": "Vertical gust for the gust envelope. 7.5 m/s is a typical "
                 "rough-air value."},
    ],
}


def run(inputs):
    try:
        mass = units.positive(inputs, "mass", "kg", "Mass")
        wing_area = units.positive(inputs, "wing_area", "m^2", "Wing area")
        span = units.positive(inputs, "span", "m", "Span")
        cl_max = units.positive(inputs, "cl_max", "", "CLmax", default=1.2)
        cd0 = units.positive(inputs, "cd0", "", "CD0", default=0.035)
        limit_load = units.positive(inputs, "limit_load", "", "Limit load",
                                    default=6.0)
        negative_limit = units.optional(inputs, "negative_limit", "", -3.0)
        cruise = units.positive(inputs, "cruise_speed", "m/s", "Cruise speed")
        v_max = units.optional(inputs, "v_max", "m/s", 0.0) or cruise * 1.4
        available_power = units.optional(inputs, "available_power", "W", 0.0)
        eta_prop = units.fraction(inputs, "prop_efficiency", 0.65)
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        gust = units.optional(inputs, "gust_velocity", "m/s", 7.5)

        negative_limit = -abs(negative_limit)
        air = atmosphere.at(altitude)
        weight = mass * G
        aspect_ratio = span ** 2 / wing_area
        oswald = aero.oswald_efficiency(aspect_ratio)
        k = aero.induced_drag_factor(aspect_ratio, oswald)
        lift_slope = aero.lift_curve_slope_3d(aspect_ratio)
        wing_loading = weight / wing_area

        v_stall = aero.stall_speed(mass, wing_area, cl_max, altitude)
        v_corner = v_stall * math.sqrt(limit_load)
        v_stall_negative = v_stall * math.sqrt(abs(negative_limit))

        r = report.Report("Turn Performance & V-n Diagram")
        r.section("Aircraft")
        r.dual("Mass", mass, "kg", "lb", 3)
        r.value("Wing loading", wing_loading, "N/m^2", 1)
        r.value("  also", units.nm2_to_ozft2(wing_loading), "oz/ft^2", 2)
        r.value("Aspect ratio", aspect_ratio, "", 2)
        r.value("CLmax", cl_max, "", 2)
        r.value("Altitude", altitude, "m", 0)

        r.section("Key Speeds")
        r.dual("Stall speed (1 g)", v_stall, "m/s", "mph", 2)
        r.dual("Manoeuvre speed (corner)", v_corner, "m/s", "mph", 2)
        r.dual("Cruise speed", cruise, "m/s", "mph", 2)
        r.dual("Never exceed (Vne)", v_max, "m/s", "mph", 2)
        r.dual("Negative stall", v_stall_negative, "m/s", "mph", 2)
        r.value("Positive limit load", limit_load, "g", 2)
        r.value("Negative limit load", negative_limit, "g", 2)
        r.blank()
        r.text("  Below the corner speed the wing stalls before the structure")
        r.text("  is threatened. Above it, full elevator can exceed the limit")
        r.text("  load, so that is the speed to respect in rough air.")

        if cruise > v_corner:
            r.warn(f"Cruise ({cruise:.1f} m/s) is above the corner speed "
                   f"({v_corner:.1f} m/s). Abrupt full control inputs at cruise "
                   "can overstress the airframe.")

        r.section("Turn Performance")
        rows = []
        for bank in (15, 30, 45, 60, 75, 80):
            radians = math.radians(bank)
            n = 1.0 / math.cos(radians)
            v_stall_bank = v_stall * math.sqrt(n)
            if cruise <= v_stall_bank:
                rows.append([f"{bank}", f"{n:.2f}", f"{v_stall_bank:.1f}",
                             "stalls", "-", "-"])
                continue
            radius = cruise ** 2 / (G * math.tan(radians))
            rate = math.degrees(G * math.tan(radians) / cruise)
            period = 360.0 / rate if rate > 0 else 0
            rows.append([f"{bank}", f"{n:.2f}", f"{v_stall_bank:.1f}",
                         f"{radius:.1f}", f"{rate:.1f}", f"{period:.1f}"])
        r.table(["Bank deg", "Load n", "Vstall m/s", "Radius m", "Rate deg/s",
                 "360 deg s"], rows)
        r.text("  Radius and rate are computed at the cruise speed given above.")

        # The tightest instantaneous turn sits at the corner speed.
        n_corner = limit_load
        radius_corner = v_corner ** 2 / (G * math.sqrt(max(n_corner ** 2 - 1, 1e-9)))
        rate_corner = math.degrees(G * math.sqrt(max(n_corner ** 2 - 1, 1e-9))
                                   / v_corner)
        r.blank()
        r.value("Tightest instantaneous turn", radius_corner, "m", 1,
                note=f"at {v_corner:.1f} m/s and {limit_load:g} g")
        r.value("Maximum turn rate", rate_corner, "deg/s", 1)

        if available_power > 0:
            r.section("Sustained Turn")
            best_n, best_v, best_radius = 1.0, cruise, float("inf")
            for i in range(1, 501):
                v = i * 0.1
                if v < v_stall or v > v_max:
                    continue
                q = 0.5 * air.density * v ** 2
                # Power available must cover drag at load factor n.
                thrust_power = available_power * eta_prop
                for j in range(1, 201):
                    n = 1.0 + j * 0.05
                    if n > limit_load:
                        break
                    cl = n * weight / (q * wing_area)
                    if cl > cl_max:
                        break
                    drag = q * wing_area * aero.drag_polar(cl, cd0, k)
                    if drag * v > thrust_power:
                        break
                    if n > best_n:
                        best_n, best_v = n, v
                        best_radius = v ** 2 / (G * math.sqrt(max(n ** 2 - 1, 1e-9)))
            if best_n > 1.0:
                r.value("Max sustained load factor", best_n, "g", 2)
                r.dual("  at speed", best_v, "m/s", "mph", 2)
                r.value("Sustained turn radius", best_radius, "m", 1)
                r.value("Sustained turn rate",
                        math.degrees(G * math.sqrt(max(best_n ** 2 - 1, 1e-9))
                                     / best_v), "deg/s", 1)
                r.value("Bank angle", math.degrees(math.acos(1.0 / best_n)),
                        "deg", 1)
                r.text("  Sustained means power balances drag; the instantaneous")
                r.text("  turn above is tighter but bleeds speed.")
            else:
                r.warn("Available power is not enough to sustain any turn "
                       "beyond level flight.")

        r.section("Gust Envelope")
        # Sharp-edged gust load factor with the standard alleviation factor.
        mu = 2.0 * wing_loading / (air.density * aero.dynamic_pressure(1, altitude)
                                   * 2 * lift_slope * 1.0)
        gust_alleviation = 0.88 * mu / (5.3 + mu) if mu > 0 else 0.8
        gust_alleviation = max(0.3, min(gust_alleviation, 1.0))
        rows = []
        for v in (v_stall, cruise, v_max):
            delta_n = (gust_alleviation * air.density * v * lift_slope * gust
                       / (2.0 * wing_loading))
            rows.append([f"{v:.1f}", f"{1 + delta_n:.2f}", f"{1 - delta_n:.2f}",
                         "EXCEEDS" if 1 + delta_n > limit_load else "ok"])
        r.value("Gust velocity", gust, "m/s", 1)
        r.value("Gust alleviation factor", gust_alleviation, "", 3)
        r.blank()
        r.table(["Speed m/s", "n up", "n down", "vs limit"], rows)
        delta_vne = (gust_alleviation * air.density * v_max * lift_slope * gust
                     / (2.0 * wing_loading))
        if 1 + delta_vne > limit_load:
            r.warn(f"A {gust:g} m/s gust at Vne would produce "
                   f"{1 + delta_vne:.1f} g, beyond the {limit_load:g} g limit. "
                   "Reduce speed in rough air.")
        else:
            r.bullet("The airframe tolerates the specified gust throughout the "
                     "speed range.")
        if wing_loading < 40:
            r.bullet("Low wing loading makes the model more gust-sensitive; it "
                     "will be thrown about in rough air even though the loads "
                     "stay modest.")

        figures = []
        if plotting.available():
            try:
                # V-n diagram: stall parabolas up to the limit, then flat.
                speeds_pos, n_pos = [], []
                speeds_neg, n_neg = [], []
                for i in range(1, 401):
                    v = v_max * i / 400.0
                    n_stall = (v / v_stall) ** 2
                    speeds_pos.append(v)
                    n_pos.append(min(n_stall, limit_load))
                    speeds_neg.append(v)
                    n_neg.append(max(-n_stall, negative_limit))
                figures.append(plotting.line_chart(
                    "V-n Diagram", "Airspeed (m/s)", "Load factor (g)",
                    [("Positive envelope", speeds_pos, n_pos),
                     ("Negative envelope", speeds_neg, n_neg),
                     ("Vne", [v_max, v_max], [negative_limit, limit_load])],
                    markers=[(f"Corner {v_corner:.1f} m/s", v_corner, limit_load),
                             (f"Stall {v_stall:.1f} m/s", v_stall, 1.0)]))

                banks = [b for b in range(5, 81)]
                radii, rates = [], []
                for bank in banks:
                    radians = math.radians(bank)
                    n = 1.0 / math.cos(radians)
                    v = max(cruise, v_stall * math.sqrt(n))
                    radii.append(v ** 2 / (G * math.tan(radians)))
                    rates.append(math.degrees(G * math.tan(radians) / v))
                figures.append(plotting.line_chart(
                    "Turn Radius vs Bank Angle", "Bank angle (deg)",
                    "Turn radius (m)", [("Radius", banks, radii)]))
            except Exception:
                r.note("Charts could not be generated.")

        return report.result(r, outputs={
            "Manoeuvre Speed": {"value": v_corner, "unit": "m/s"},
            "Never Exceed Speed": {"value": v_max, "unit": "m/s"},
            "Limit Load Factor": {"value": limit_load, "unit": "g"},
            "Min Turn Radius": {"value": radius_corner, "unit": "m"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
