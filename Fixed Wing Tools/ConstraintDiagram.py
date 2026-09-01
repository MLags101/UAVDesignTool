"""
Constraint Diagram (Wing Loading vs Power Loading)

The proper way to choose wing area and motor power together. Each requirement
-- stall speed, takeoff distance, climb rate, cruise speed, sustained turn --
becomes a curve in the wing-loading / power-to-weight plane. The design point
must sit above every curve; the cheapest aircraft that meets the brief sits
exactly on the binding constraint.

This replaces single-point sizing, which can only tell you the area for one
chosen speed and cannot show which requirement is actually driving the design.
"""

import math

from uavlib import aero, atmosphere, plotting, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Constraint Diagram",
    "category": "Fixed Wing / Sizing",
    "description": (
        "Plots stall, takeoff, climb, cruise and turn constraints on a wing "
        "loading versus power loading chart, and reports the design point and "
        "which requirement drives it."
    ),
    "inputs": [
        {"key": "mass", "label": "Design Mass", "unit": "kg", "type": "number"},
        {"key": "altitude", "label": "Design Altitude", "unit": "m",
         "type": "number", "default": "0"},
        {"key": "cl_max", "label": "Max Lift Coefficient", "type": "number",
         "default": "1.2", "help": "3D value. Roughly 0.9x the aerofoil's 2D Clmax."},
        {"key": "v_stall", "label": "Required Stall Speed", "unit": "m/s",
         "type": "number", "help": "Sets the maximum allowable wing loading."},
        {"key": "v_cruise", "label": "Cruise Speed", "unit": "m/s", "type": "number"},
        {"key": "climb_rate", "label": "Required Climb Rate", "unit": "m/s",
         "type": "number", "default": "3"},
        {"key": "turn_radius", "label": "Sustained Turn Radius", "unit": "m",
         "type": "number", "default": "25"},
        {"key": "takeoff_distance", "label": "Takeoff Ground Roll", "unit": "m",
         "type": "number", "default": "40",
         "help": "Leave blank for hand launch."},
        {"key": "cd0", "label": "Parasite Drag (CD0)", "type": "number",
         "default": "0.035"},
        {"key": "aspect_ratio", "label": "Aspect Ratio", "type": "number",
         "default": "8"},
        {"key": "prop_efficiency", "label": "Propeller Efficiency", "type": "number",
         "default": "0.65"},
    ],
}

# Wing loadings swept across the chart, N/m^2. Model aircraft live in the
# 20-200 N/m^2 band: park flyers at the bottom, fast EDF jets at the top.
WS_MIN, WS_MAX, WS_STEPS = 15.0, 220.0, 90


def run(inputs):
    try:
        mass = units.positive(inputs, "mass", "kg", "Design mass")
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        cl_max = units.positive(inputs, "cl_max", "", "CLmax", default=1.2)
        v_stall = units.parse(inputs.get("v_stall"), "m/s", None)
        v_cruise = units.positive(inputs, "v_cruise", "m/s", "Cruise speed")
        climb_rate = units.optional(inputs, "climb_rate", "m/s", 3.0)
        turn_radius = units.optional(inputs, "turn_radius", "m", 25.0)
        takeoff = units.parse(inputs.get("takeoff_distance"), "m", None)
        cd0 = units.positive(inputs, "cd0", "", "CD0", default=0.035)
        aspect_ratio = units.positive(inputs, "aspect_ratio", "", "Aspect ratio",
                                      default=8.0)
        eta_prop = units.optional(inputs, "prop_efficiency", "", 0.65) or 0.65

        air = atmosphere.at(altitude)
        rho = air.density
        weight = mass * G
        oswald = aero.oswald_efficiency(aspect_ratio)
        k = aero.induced_drag_factor(aspect_ratio, oswald)

        wing_loadings = [WS_MIN + (WS_MAX - WS_MIN) * i / (WS_STEPS - 1)
                         for i in range(WS_STEPS)]

        def power_to_weight_cruise(ws):
            """P/W to hold cruise speed: drag power at that wing loading."""
            q = 0.5 * rho * v_cruise ** 2
            drag_to_weight = q * cd0 / ws + k * ws / q
            return drag_to_weight * v_cruise / eta_prop

        def power_to_weight_climb(ws):
            """P/W to climb at the required rate, at best-climb speed."""
            v = math.sqrt(2.0 * ws / (rho * math.sqrt(3.0 * cd0 / k)))
            q = 0.5 * rho * v ** 2
            drag_to_weight = q * cd0 / ws + k * ws / q
            return (climb_rate + v * drag_to_weight) / eta_prop

        def power_to_weight_turn(ws):
            """P/W for a sustained level turn of the required radius."""
            v = v_cruise
            load_factor = math.sqrt(1.0 + (v ** 2 / (G * turn_radius)) ** 2)
            q = 0.5 * rho * v ** 2
            drag_to_weight = q * cd0 / ws + k * load_factor ** 2 * ws / q
            return drag_to_weight * v / eta_prop

        def power_to_weight_takeoff(ws):
            """P/W for the required ground roll, via a rolling-friction model."""
            v_liftoff = 1.2 * math.sqrt(2.0 * ws / (rho * cl_max))
            # Average acceleration needed over the roll.
            acceleration = v_liftoff ** 2 / (2.0 * takeoff)
            # Thrust must overcome inertia, rolling friction and drag at 0.7 V.
            v_avg = 0.7 * v_liftoff
            q = 0.5 * rho * v_avg ** 2
            drag_to_weight = q * cd0 / ws + k * ws / q
            thrust_to_weight = acceleration / G + 0.04 + drag_to_weight
            return thrust_to_weight * v_avg / eta_prop

        constraints = [
            ("Cruise speed", [power_to_weight_cruise(ws) for ws in wing_loadings]),
            (f"Climb {climb_rate:g} m/s",
             [power_to_weight_climb(ws) for ws in wing_loadings]),
            (f"Turn r={turn_radius:g} m",
             [power_to_weight_turn(ws) for ws in wing_loadings]),
        ]
        if takeoff and takeoff > 0:
            constraints.append((f"Takeoff {takeoff:g} m",
                                [power_to_weight_takeoff(ws) for ws in wing_loadings]))

        # The stall requirement caps wing loading rather than setting a P/W.
        ws_stall = None
        if v_stall and v_stall > 0:
            ws_stall = 0.5 * rho * v_stall ** 2 * cl_max

        # The design point sits at the highest allowable wing loading (smallest
        # wing) with just enough power to satisfy every constraint there.
        ws_design = ws_stall if ws_stall else WS_MAX * 0.5
        ws_design = max(WS_MIN, min(ws_design, WS_MAX))
        pw_design = max(values[min(range(len(wing_loadings)),
                                   key=lambda i: abs(wing_loadings[i] - ws_design))]
                        for _, values in constraints)
        driving = max(constraints,
                      key=lambda c: c[1][min(range(len(wing_loadings)),
                                             key=lambda i: abs(wing_loadings[i] - ws_design))])

        r = report.Report("Constraint Diagram")
        r.section("Design Conditions")
        r.value("Mass", mass, "kg", 3)
        r.dual("Weight", weight, "N", "lbf", 2)
        r.value("Altitude", altitude, "m", 0)
        r.value("Air density", rho, "kg/m^3", 4)
        r.value("CLmax", cl_max, "", 2)
        r.value("CD0", cd0, "", 4)
        r.value("Aspect ratio", aspect_ratio, "", 2)
        r.value("Oswald efficiency", oswald, "", 3)
        r.note(aero.oswald_note(aspect_ratio))

        r.section("Design Point")
        if ws_stall:
            r.value("Wing loading limit (stall)", ws_stall, "N/m^2", 1)
            r.value("  also", units.nm2_to_ozft2(ws_stall), "oz/ft^2", 2)
        r.value("Selected wing loading", ws_design, "N/m^2", 1)
        r.value("Required wing area", weight / ws_design, "m^2", 4)
        r.value("Required power loading", pw_design, "W/N", 3)
        r.value("Required power", pw_design * weight, "W", 1)
        r.value("Power to mass", pw_design * weight / mass, "W/kg", 1)
        r.value("Driving constraint", driving[0])

        r.section("Constraint Comparison at Design Wing Loading")
        index = min(range(len(wing_loadings)),
                    key=lambda i: abs(wing_loadings[i] - ws_design))
        rows = []
        for label, values in constraints:
            power = values[index] * weight
            rows.append([label, f"{values[index]:.3f}", f"{power:.0f}",
                         "<-- drives" if label == driving[0] else ""])
        r.table(["Constraint", "P/W (W/N)", "Power (W)", ""], rows)

        r.section("Interpretation")
        r.bullet("Every point above all the curves meets the brief. Moving right "
                 "means a smaller wing; moving up means a bigger motor.")
        r.bullet(f"'{driving[0]}' sets the power here. Relaxing that requirement "
                 "is the cheapest way to shrink the propulsion system.")
        if ws_stall:
            r.bullet("Stall speed caps wing loading: a wing smaller than "
                     f"{weight / ws_stall:.3f} m^2 cannot meet the stall target.")

        # Power expressed the way RC builders actually quote it.
        watts_per_kg = pw_design * weight / mass
        watts_per_lb = watts_per_kg * 0.45359237
        r.bullet(f"Power works out at {watts_per_kg:.0f} W/kg "
                 f"({watts_per_lb:.0f} W/lb). For reference: 50-80 W/lb is "
                 "trainer and scale, 80-120 W/lb sport aerobatic, and 150+ W/lb "
                 "gives unlimited vertical.")
        if watts_per_lb < 50:
            r.bullet("That is below the usual trainer band because the climb "
                     "and turn targets set here are modest. Raise the climb "
                     "rate if you want lively performance.")

        wl = units.nm2_to_ozft2(ws_design)
        if wl < 10:
            r.bullet(f"{wl:.1f} oz/ft^2 is a light park-flyer loading: docile, "
                     "but easily upset by wind.")
        elif wl < 20:
            r.bullet(f"{wl:.1f} oz/ft^2 is a typical sport/trainer loading.")
        elif wl < 35:
            r.bullet(f"{wl:.1f} oz/ft^2 is a fast sport loading; expect higher "
                     "landing speeds and a need for smooth runways.")
        else:
            r.bullet(f"{wl:.1f} oz/ft^2 is a high loading, typical of jets and "
                     "pylon racers. Landings will be fast.")

        figures = []
        if plotting.available():
            try:
                series = [(label, wing_loadings, values) for label, values in constraints]
                figures.append(plotting.filled_region_chart(
                    "Constraint Diagram",
                    "Wing loading W/S (N/m^2)",
                    "Power loading P/W (W/N)",
                    series,
                    design_point=("Design point", ws_design, pw_design),
                    feasible="above"))
            except Exception:
                r.note("Chart could not be generated.")

        return report.result(r, outputs={
            "Wing Area (S)": {"value": weight / ws_design, "unit": "m^2"},
            "Wing Loading": {"value": ws_design, "unit": "N/m^2"},
            "Required Power": {"value": pw_design * weight, "unit": "W"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
