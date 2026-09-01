"""
Stall Speed and Flight State Analyser

Rebuilt on the shared aerodynamics library. Changes from the earlier version:

* The lift-curve slope is now the finite-wing value from lifting-line theory,
  rather than a hardcoded constant.
* CLmax is distinguished from the aerofoil's 2D Clmax, which a finite wing
  never reaches -- roughly 0.9 of it, less with sweep.
* Stall speed is reported across load factor, since a wing stalls at a higher
  speed the harder it is turning.
"""

import math

from uavlib import aero, atmosphere, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Stall & Flight State Analyser",
    "category": "Fixed Wing / Performance",
    "description": (
        "Stall speed at load factor, plus the lift, drag and angle of attack at "
        "a given flight state. Reports approach speed, manoeuvre speed and how "
        "close the current condition sits to the stall."
    ),
    "inputs": [
        {"key": "mass", "label": "Total Mass", "unit": "kg", "type": "number"},
        {"key": "area", "label": "Wing Area (S)", "unit": "m^2", "type": "number"},
        {"key": "span", "label": "Wing Span (b)", "unit": "m", "type": "number"},
        {"key": "cl_max_2d", "label": "Aerofoil Clmax (2D)", "type": "number",
         "default": "1.4", "help": "From the aerofoil polar at your Reynolds "
                                   "number. The 3D wing gets about 0.9 of this."},
        {"key": "sweep", "label": "Quarter-Chord Sweep", "unit": "deg",
         "type": "number", "default": "0"},
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number",
         "default": "0"},
        {"key": "velocity", "label": "Current Airspeed", "unit": "m/s",
         "type": "number", "help": "Optional: gives the current flight state."},
        {"key": "cd0", "label": "Parasite Drag (CD0)", "type": "number",
         "default": "0.035"},
        {"key": "load_factor", "label": "Load Factor", "unit": "g",
         "type": "number", "default": "1.0"},
        {"key": "limit_load", "label": "Structural Limit Load", "unit": "g",
         "type": "number", "default": "6.0",
         "help": "Used to find the manoeuvre (corner) speed."},
    ],
}


def run(inputs):
    try:
        mass = units.positive(inputs, "mass", "kg", "Mass")
        area = units.positive(inputs, "area", "m^2", "Wing area")
        span = units.positive(inputs, "span", "m", "Wing span")
        cl_max_2d = units.positive(inputs, "cl_max_2d", "", "Aerofoil Clmax",
                                   default=1.4)
        sweep = units.optional(inputs, "sweep", "deg", 0.0)
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        velocity = units.optional(inputs, "velocity", "m/s", 0.0)
        cd0 = units.positive(inputs, "cd0", "", "CD0", default=0.035)
        load_factor = units.optional(inputs, "load_factor", "", 1.0) or 1.0
        limit_load = units.optional(inputs, "limit_load", "", 6.0) or 6.0

        air = atmosphere.at(altitude)
        aspect_ratio = span ** 2 / area
        weight = mass * G

        cl_max = aero.cl_max_3d(cl_max_2d, sweep)
        lift_slope = aero.lift_curve_slope_3d(aspect_ratio, sweep_qc_deg=sweep)
        oswald = aero.oswald_efficiency(aspect_ratio, sweep)
        k = aero.induced_drag_factor(aspect_ratio, oswald)

        v_stall = aero.stall_speed(mass, area, cl_max, altitude)
        v_stall_n = aero.stall_speed(mass, area, cl_max, altitude, load_factor)
        v_corner = aero.stall_speed(mass, area, cl_max, altitude, limit_load)

        r = report.Report("Flight State")
        r.section("Configuration")
        r.value("Mass", mass, "kg", 3)
        r.dual("Weight", weight, "N", "lbf", 2)
        r.value("Wing area", area, "m^2", 4)
        r.value("Aspect ratio", aspect_ratio, "", 2)
        r.value("Wing loading", weight / area, "N/m^2", 1)
        r.value("Altitude", altitude, "m", 0)
        r.value("Air density", air.density, "kg/m^3", 4)

        r.section("Lift Characteristics")
        r.value("Aerofoil Clmax (2D)", cl_max_2d, "", 3)
        r.value("Wing CLmax (3D)", cl_max, "", 3,
                note=f"{100 * cl_max / cl_max_2d:.0f}% of 2D")
        r.value("Lift-curve slope", lift_slope, "per rad", 3)
        r.value("  per degree", math.radians(1) * lift_slope, "", 5)
        r.value("Oswald efficiency", oswald, "", 3)

        r.section("Stall Speeds")
        r.dual("Stall speed (1 g)", v_stall, "m/s", "mph", 2)
        r.dual("Approach speed (1.3 Vs)", 1.3 * v_stall, "m/s", "mph", 2)
        if abs(load_factor - 1.0) > 1e-6:
            r.dual(f"Stall speed at {load_factor:g} g", v_stall_n, "m/s", "mph", 2)
        r.dual(f"Manoeuvre speed at {limit_load:g} g", v_corner, "m/s", "mph", 2)
        r.text("  Above the manoeuvre speed, full control deflection can")
        r.text("  overstress the airframe before the wing stalls.")

        r.blank()
        rows = []
        for n in sorted({1.0, 1.5, 2.0, 3.0, 4.0, limit_load}):
            v = aero.stall_speed(mass, area, cl_max, altitude, n)
            bank = math.degrees(math.acos(1.0 / n)) if n >= 1 else 0.0
            rows.append([f"{n:.1f}", f"{v:.2f}", f"{units.ms_to_mph(v):.1f}",
                         f"{bank:.0f}"])
        r.table(["Load n", "Vs m/s", "Vs mph", "Bank deg"], rows)

        if velocity > 0:
            q = 0.5 * air.density * velocity ** 2
            cl = aero.cl_required(mass, area, velocity, altitude, load_factor)
            cd = aero.drag_polar(cl, cd0, k)
            drag = q * area * cd
            alpha = math.degrees(cl / lift_slope)

            r.section("Current Flight State")
            r.dual("Airspeed", velocity, "m/s", "mph", 2)
            r.value("Load factor", load_factor, "g", 2)
            r.value("Dynamic pressure", q, "Pa", 1)
            r.value("Required CL", cl, "", 4)
            r.value("CL / CLmax", cl / cl_max, "", 3)
            r.value("Total CD", cd, "", 5)
            r.value("Lift", q * area * cl, "N", 2)
            r.value("Drag", drag, "N", 3)
            r.value("L/D", cl / cd, "", 2)
            r.value("Angle of attack (from zero lift)", alpha, "deg", 2)
            r.value("Power required (aero)", drag * velocity, "W", 1)
            r.value("Speed / stall speed", velocity / v_stall_n, "", 2)

            if velocity < v_stall_n:
                r.warn(f"BELOW STALL SPEED at {load_factor:g} g. The wing "
                       "cannot generate the required lift.")
            elif cl > cl_max * 0.9:
                r.warn("Within 10% of CLmax -- the wing is close to the stall.")
            if velocity > v_corner:
                r.warn("Above manoeuvre speed: full control deflection risks "
                       "structural damage.")

            best_ld, cl_best = aero.ld_max(cd0, k)
            v_best = aero.stall_speed_at_cl(mass, area, cl_best, altitude)
            r.blank()
            r.value("Best L/D available", best_ld, "", 2)
            r.dual("  at speed", v_best, "m/s", "mph", 2)
            if velocity > v_best * 1.3:
                r.bullet("Flying well above best-L/D speed: parasite drag "
                         "dominates. Slowing down would extend range.")
            elif velocity < v_best * 0.8:
                r.bullet("Flying well below best-L/D speed: induced drag "
                         "dominates, on the back side of the power curve.")

        return report.result(r, outputs={
            "Stall Speed": {"value": v_stall, "unit": "m/s"},
            "Wing CLmax": {"value": cl_max},
            "Approach Speed": {"value": 1.3 * v_stall, "unit": "m/s"},
            "Manoeuvre Speed": {"value": v_corner, "unit": "m/s"},
        })

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
