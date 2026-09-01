"""
Wing Area Sizing

Sizes the wing for a cruise condition and cross-checks the result against
stall speed and Reynolds number. Two corrections from the earlier version:

* The input called "safety factor" is really a load factor -- the g the wing is
  being sized to carry -- and is now named accordingly.
* Wing loading was reported as mass/area with the load factor folded in, mixing
  kg/m^2 with a dimensionless multiplier. Wing loading is now reported as a
  proper W/S in N/m^2, alongside the oz/ft^2 that model specifications use.

For choosing wing area and power together, use the Constraint Diagram tool
instead: single-point sizing cannot show which requirement is really binding.
"""

import math

from uavlib import aero, atmosphere, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Wing Area Sizing",
    "category": "Fixed Wing / Sizing",
    "description": (
        "Computes the wing area needed for steady cruise at a chosen lift "
        "coefficient, then checks the resulting stall speed, wing loading and "
        "Reynolds number. Air density follows the standard atmosphere."
    ),
    "inputs": [
        {"key": "mass", "label": "Total Mass", "unit": "kg", "type": "number"},
        {"key": "velocity", "label": "Cruise Speed", "unit": "m/s", "type": "number"},
        {"key": "altitude", "label": "Cruise Altitude", "unit": "m",
         "type": "number", "default": "0"},
        {"key": "cl", "label": "Cruise Lift Coefficient", "type": "number",
         "default": "0.5",
         "help": "0.3-0.5 for fast sport models, 0.6-0.9 for gliders and "
                 "slow flyers."},
        {"key": "load_factor", "label": "Design Load Factor (n)", "type": "number",
         "default": "1.0",
         "help": "1.0 sizes for level cruise. Use the manoeuvre limit (4-6 g) "
                 "only when sizing structure, not planform."},
        {"key": "cl_max", "label": "Max Lift Coefficient", "type": "number",
         "default": "1.2", "help": "3D value, for the stall-speed check."},
        {"key": "aspect_ratio", "label": "Aspect Ratio", "type": "number",
         "default": "8", "help": "Used to report span and chord."},
    ],
}


def run(inputs):
    try:
        mass = units.positive(inputs, "mass", "kg", "Mass")
        velocity = units.positive(inputs, "velocity", "m/s", "Cruise speed")
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        cl = units.positive(inputs, "cl", "", "Cruise lift coefficient", default=0.5)
        load_factor = units.optional(inputs, "load_factor", "", 1.0) or 1.0
        cl_max = units.positive(inputs, "cl_max", "", "CLmax", default=1.2)
        aspect_ratio = units.positive(inputs, "aspect_ratio", "", "Aspect ratio",
                                      default=8.0)

        if cl > cl_max:
            return report.error(
                f"Cruise CL ({cl:g}) cannot exceed CLmax ({cl_max:g}); the wing "
                "would already be stalled at the cruise condition.")

        air = atmosphere.at(altitude)
        weight = mass * G
        q = 0.5 * air.density * velocity ** 2

        # S = n*W / (q * CL)
        area = load_factor * weight / (q * cl)

        span = math.sqrt(aspect_ratio * area)
        mean_chord = area / span
        wing_loading = weight / area           # N/m^2
        v_stall = aero.stall_speed(mass, area, cl_max, altitude)
        re = atmosphere.reynolds(velocity, mean_chord, altitude)
        re_stall = atmosphere.reynolds(v_stall, mean_chord, altitude)

        r = report.Report("Wing Area Sizing")
        r.section("Design Condition")
        r.value("Mass", mass, "kg", 3)
        r.dual("Weight", weight, "N", "lbf", 2)
        r.dual("Cruise speed", velocity, "m/s", "mph", 2)
        r.value("Altitude", altitude, "m", 0)
        r.value("Air density", air.density, "kg/m^3", 4)
        r.value("Dynamic pressure (q)", q, "Pa", 1)
        r.value("Cruise CL", cl, "", 3)
        r.value("Load factor (n)", load_factor, "g", 2)

        r.section("Result")
        r.dual("Required wing area (S)", area, "m^2", "ft^2", 4)
        r.value("Span at AR " + f"{aspect_ratio:g}", span, "m", 3)
        r.value("Mean chord", mean_chord, "m", 4)
        r.value("Wing loading (W/S)", wing_loading, "N/m^2", 1)
        r.value("  also", units.nm2_to_ozft2(wing_loading), "oz/ft^2", 2)
        r.value("  also", mass / area, "kg/m^2", 2)

        r.section("Checks")
        r.dual("Stall speed at CLmax", v_stall, "m/s", "mph", 2)
        r.value("Cruise / stall margin", velocity / v_stall, "", 2)
        r.dual("Approach speed (1.3 Vs)", 1.3 * v_stall, "m/s", "mph", 2)
        r.value("Re at mean chord (cruise)", re, "", 0)
        r.value("Re at mean chord (stall)", re_stall, "", 0)

        if velocity / v_stall < 1.3:
            r.warn("Cruise is less than 1.3x the stall speed. There is very "
                   "little margin for turbulence or manoeuvre.")
        elif velocity / v_stall > 3.0:
            r.bullet("Cruise is well above stall; the wing is larger than the "
                     "cruise condition alone requires, which favours slow "
                     "flight and short landings.")

        r.blank()
        r.text(f"  {atmosphere.reynolds_note(re_stall)}")
        if re_stall < 70_000:
            r.warn("Reynolds number at the stall falls in the range where "
                   "CLmax collapses. The real stall speed will be higher than "
                   "calculated here.")

        loading_ozft2 = units.nm2_to_ozft2(wing_loading)
        r.section("Wing Loading Context")
        r.table(["Class", "oz/ft^2", "N/m^2"], [
            ["Indoor / slow flyer", "< 6", "< 18"],
            ["Park flyer / trainer", "6 - 14", "18 - 42"],
            ["Sport", "14 - 22", "42 - 66"],
            ["Fast sport / warbird", "22 - 35", "66 - 105"],
            ["Jet / pylon racer", "> 35", "> 105"],
        ])
        r.value("This design", loading_ozft2, "oz/ft^2", 2)

        return report.result(r, outputs={
            "Wing Area (S)": {"value": area, "unit": "m^2"},
            "Wing Span (b)": {"value": span, "unit": "m"},
            "Wing Loading": {"value": wing_loading, "unit": "N/m^2"},
            "Stall Speed": {"value": v_stall, "unit": "m/s"},
        })

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
