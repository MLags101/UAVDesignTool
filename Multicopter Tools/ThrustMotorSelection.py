"""
Thrust-to-Weight and Motor Selection

Works out how much thrust each motor must produce for a target thrust-to-weight
ratio, what that costs in power and current, and whether a candidate motor and
propeller combination can deliver it.

Thrust-to-weight is the single number that decides how a multirotor feels:
below 2:1 it can barely hold station in wind, and above 4:1 it is aerobatic.
"""

from uavlib import battery, geometry, plotting, propulsion, report, units
from uavlib import atmosphere
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Thrust & Motor Selection",
    "category": "Multirotor / Propulsion",
    "description": (
        "Required thrust per motor for a target thrust-to-weight ratio, with "
        "hover throttle, current draw and the margin left for manoeuvre. "
        "Checks a candidate motor/prop against the requirement."
    ),
    "inputs": [
        {"key": "layout", "label": "Frame Layout", "type": "choice",
         "choices": list(geometry.LAYOUTS), "default": "Quadcopter X"},
        {"key": "mass", "label": "All-Up Mass", "unit": "kg", "type": "number"},
        {"key": "target_twr", "label": "Target Thrust-to-Weight", "type": "number",
         "default": "2.0", "min": 1.1, "max": 12.0,
         "help": "2:1 camera work, 3:1 sport, 5:1+ racing and freestyle."},
        {"key": "rotor_diameter", "label": "Rotor Diameter", "unit": "m",
         "type": "number", "help": "Accepts '10 in' or '10x4.7'."},
        {"key": "rotor_pitch", "label": "Rotor Pitch", "unit": "m",
         "type": "number", "help": "Accepts inches, e.g. '4.7 in'."},
        {"key": "kv", "label": "Motor Kv", "unit": "rpm/V", "type": "number"},
        {"key": "cells", "label": "Battery Cells (S)", "type": "number",
         "default": "4"},
        {"key": "figure_of_merit", "label": "Figure of Merit", "type": "number",
         "default": "0.65", "min": 0.3, "max": 0.85},
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number",
         "default": "0"},
        {"key": "motor_eff", "label": "Motor Efficiency", "type": "number",
         "default": "0.80"},
        {"key": "capacity", "label": "Battery Capacity", "unit": "Ah",
         "type": "number", "help": "Optional, for the C-rate check."},
        {"key": "pack_c_rating", "label": "Pack C Rating", "type": "number",
         "help": "Optional, for the C-rate check."},
    ],
}

TWR_BANDS = (
    (1.5, "UNFLYABLE in practice. Below 1.5:1 there is no authority left for "
          "wind or manoeuvre once hover is paid for."),
    (2.0, "Marginal. Gentle flight in still air only; a gust can exceed the "
          "available thrust."),
    (3.0, "Camera platform. Smooth, efficient, adequate margin for wind."),
    (5.0, "Sport. Responsive, good climb rate, tolerant of wind and payload."),
    (8.0, "Freestyle / racing. Very aggressive; hover sits low on the throttle "
          "stick which makes fine control harder."),
    (float("inf"), "Extreme. Beyond about 8:1 the airframe is thrust-limited by "
                   "structure and control resolution, not power."),
)


def twr_note(twr):
    for threshold, note in TWR_BANDS:
        if twr < threshold:
            return note
    return TWR_BANDS[-1][1]


def run(inputs):
    try:
        layout_name = inputs.get("layout") or "Quadcopter X"
        frame = geometry.layout(layout_name)
        mass = units.positive(inputs, "mass", "kg", "All-up mass")
        target_twr = units.positive(inputs, "target_twr", "", "Target T/W",
                                    default=2.0)
        diameter = units.positive(inputs, "rotor_diameter", "m", "Rotor diameter")
        pitch = units.optional(inputs, "rotor_pitch", "m", 0.0)
        kv = units.optional(inputs, "kv", "", 0.0)
        cells = int(units.optional(inputs, "cells", "", 4) or 4)
        fm = units.optional(inputs, "figure_of_merit", "", 0.65) or 0.65
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        eta_motor = units.fraction(inputs, "motor_eff", 0.80)
        capacity = units.optional(inputs, "capacity", "Ah", 0.0)
        pack_c = units.optional(inputs, "pack_c_rating", "", 0.0)

        weight = mass * G
        voltage = battery.nominal_voltage(cells, "LiPo")

        effective = frame.motors * (1 - geometry.COAXIAL_PENALTY) \
            if frame.coaxial else frame.motors
        hover_thrust = weight / effective
        required_thrust = hover_thrust * target_twr

        # Momentum theory works per disk, and a coaxial pair shares one disk.
        disks = geometry.disk_count(frame)
        coaxial_factor = (1.0 / propulsion.COAXIAL_EFFICIENCY
                          if frame.coaxial else 1.0)
        hover_shaft = (propulsion.hover_power(weight, diameter, fm, altitude, disks)
                       * coaxial_factor / frame.motors)
        max_shaft = (propulsion.hover_power(weight * target_twr, diameter, fm,
                                            altitude, disks)
                     * coaxial_factor / frame.motors)
        hover_elec = propulsion.electrical_power(hover_shaft, eta_motor)
        max_elec = propulsion.electrical_power(max_shaft, eta_motor)

        r = report.Report("Thrust & Motor Selection")
        r.section("Requirement")
        r.value("Layout", f"{layout_name} ({frame.motors} motors)")
        r.dual("All-up mass", mass, "kg", "lb", 3)
        r.dual("Weight", weight, "N", "lbf", 2)
        r.value("Target thrust-to-weight", target_twr, ":1", 2)
        if frame.coaxial:
            r.value("Effective rotors", effective, "", 2,
                    note="coaxial penalty applied")

        r.section("Per-Motor Thrust")
        r.value("Hover thrust per motor", hover_thrust, "N", 3)
        r.value("  in grams", hover_thrust / G * 1000, "g", 0)
        r.value("Required max thrust per motor", required_thrust, "N", 3)
        r.value("  in grams", required_thrust / G * 1000, "g", 0)
        r.value("Total required thrust", required_thrust * effective, "N", 2)
        r.value("Hover throttle", 100.0 / target_twr, "%", 1)
        r.blank()
        r.text(f"  {twr_note(target_twr)}")

        r.section("Power Estimate")
        r.value("Hover shaft power per motor", hover_shaft, "W", 1)
        r.value("Max shaft power per motor", max_shaft, "W", 1)
        r.value("Hover electrical (all motors)", hover_elec * frame.motors, "W", 1)
        r.value("Max electrical (all motors)", max_elec * frame.motors, "W", 1)
        r.value("Hover current", hover_elec * frame.motors / voltage, "A", 2)
        r.value("Max current", max_elec * frame.motors / voltage, "A", 2)
        r.value("Max current per motor", max_elec / voltage, "A", 2)
        r.value("Pack voltage assumed", voltage, "V", 2, note=f"{cells}S nominal")

        esc_rating = max_elec / voltage * 1.3
        r.value("Suggested ESC rating", esc_rating, "A", 0,
                note="30% margin")
        wire = battery.recommend_wire(max_elec * frame.motors / voltage)
        r.value("Suggested main wire", f"AWG {wire['awg']}", "",
                note=f"{wire['rated_a']:.0f} A rated")

        # Check the candidate propeller against the requirement.
        if pitch > 0 and kv > 0:
            rpm = propulsion.motor_rpm(kv, voltage)
            available = propulsion.static_thrust(diameter, pitch, rpm, altitude)
            prop_shaft = propulsion.static_shaft_power(diameter, pitch, rpm, altitude)
            ct, cp = propulsion.static_coefficients(pitch / diameter)

            r.section("Candidate Motor and Propeller")
            r.value("Motor Kv", kv, "rpm/V", 0)
            r.dual("Propeller", diameter, "m", "in", 4)
            r.value("Pitch/diameter ratio", pitch / diameter, "", 3)
            r.value("Estimated loaded RPM", rpm, "rpm", 0)
            r.value("Thrust coefficient Ct", ct, "", 4)
            r.value("Power coefficient Cp", cp, "", 4)
            r.value("Available thrust per motor", available, "N", 3)
            r.value("  in grams", available / G * 1000, "g", 0)
            r.value("Shaft power at full throttle", prop_shaft, "W", 1)
            r.value("Tip speed", 3.14159 * diameter * rpm / 60.0, "m/s", 1)
            r.value("Pitch speed", propulsion.pitch_speed(rpm, pitch), "m/s", 1)

            achieved = available * effective / weight
            r.blank()
            r.value("Achieved thrust-to-weight", achieved, ":1", 2)
            if available < required_thrust:
                r.warn(f"This combination falls short: {available / G * 1000:.0f} g "
                       f"per motor against {required_thrust / G * 1000:.0f} g "
                       "required. Increase Kv, cell count or prop size.")
            else:
                r.bullet(f"Meets the requirement with "
                         f"{100 * (available / required_thrust - 1):.0f}% to spare.")

            tip_speed = 3.14159 * diameter * rpm / 60.0
            if tip_speed > 200:
                r.warn(f"Tip speed of {tip_speed:.0f} m/s is above about Mach "
                       "0.6. Expect a sharp rise in noise and a fall in "
                       "efficiency; reduce Kv or prop diameter.")

            if capacity > 0:
                total_current = prop_shaft / eta_motor * frame.motors / voltage
                required_c = battery.c_rate(total_current, capacity)
                r.blank()
                r.value("Full-throttle current", total_current, "A", 1)
                r.value("Required C rate", required_c, "C", 1)
                if pack_c > 0:
                    r.text(f"  {battery.c_rating_note(required_c, pack_c)}")

        r.section("Thrust-to-Weight Reference")
        r.table(["T/W", "Hover throttle", "Use"], [
            ["1.5:1", "67%", "Not recommended"],
            ["2:1", "50%", "Camera / survey"],
            ["3:1", "33%", "General sport"],
            ["5:1", "20%", "Freestyle"],
            ["8:1+", "13%", "Racing"],
        ])

        figures = []
        if plotting.available() and kv > 0 and pitch > 0:
            try:
                throttles, thrusts, powers = [], [], []
                for i in range(1, 21):
                    fraction = i / 20.0
                    rpm_i = propulsion.motor_rpm(kv, voltage * fraction)
                    throttles.append(fraction * 100)
                    thrusts.append(propulsion.static_thrust(
                        diameter, pitch, rpm_i, altitude) / G * 1000)
                    powers.append(propulsion.static_shaft_power(
                        diameter, pitch, rpm_i, altitude))
                figures.append(plotting.line_chart(
                    "Thrust and Power vs Throttle", "Throttle (%)",
                    "Thrust per motor (g)", [("Thrust", throttles, thrusts)],
                    markers=[(f"Hover {100 / target_twr:.0f}%",
                              100 / target_twr, hover_thrust / G * 1000)]))
            except Exception:
                r.note("Chart could not be generated.")

        return report.result(r, outputs={
            "Thrust per Motor Required": {"value": required_thrust, "unit": "N"},
            "Hover Thrust per Motor": {"value": hover_thrust, "unit": "N"},
            "Hover Throttle": {"value": 100.0 / target_twr, "unit": "%"},
            "Max Current": {"value": max_elec * frame.motors / voltage, "unit": "A"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
