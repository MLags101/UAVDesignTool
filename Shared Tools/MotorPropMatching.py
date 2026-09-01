"""
Motor and Propeller Matching

Checks that a motor, propeller, battery and ESC actually suit one another. The
usual failure is a propeller that loads the motor beyond its thermal limit --
the combination flies, briefly, and then the motor burns out.

Static thrust and power come from coefficient form (Ct, Cp) rather than a
one-line empirical fit, so the numbers track published propeller data.
"""

import math

from uavlib import battery, plotting, propulsion, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Motor & Propeller Matching",
    "category": "Shared / Propulsion",
    "description": (
        "Loaded RPM, static thrust, shaft power, current and tip speed for a "
        "motor and propeller on a given pack. Flags overloading, excessive tip "
        "speed, and a pitch speed mismatched to the intended cruise."
    ),
    "inputs": [
        {"key": "kv", "label": "Motor Kv", "unit": "rpm/V", "type": "number"},
        {"key": "motor_watts", "label": "Motor Power Rating", "unit": "W",
         "type": "number", "help": "Manufacturer's continuous rating."},
        {"key": "motor_max_current", "label": "Motor Max Current", "unit": "A",
         "type": "number", "help": "Optional."},
        {"key": "cells", "label": "Battery Cells (S)", "type": "number",
         "default": "4"},
        {"key": "chemistry", "label": "Chemistry", "type": "choice",
         "choices": ["LiPo", "Li-ion", "LiHV", "LiFePO4", "NiMH"],
         "default": "LiPo"},
        {"key": "diameter", "label": "Propeller Diameter", "unit": "m",
         "type": "number", "help": "Accepts '10 in' or '10x4.7'."},
        {"key": "pitch", "label": "Propeller Pitch", "unit": "m",
         "type": "number", "help": "Accepts inches."},
        {"key": "load_factor", "label": "RPM Under Load", "unit": "fraction",
         "type": "number", "default": "0.85",
         "help": "Loaded RPM as a fraction of Kv x V. 0.80-0.90 is typical."},
        {"key": "motor_eff", "label": "Motor Efficiency", "type": "number",
         "default": "0.80"},
        {"key": "cruise_speed", "label": "Intended Cruise Speed", "unit": "m/s",
         "type": "number", "help": "Optional. Checks the pitch match."},
        {"key": "esc_rating", "label": "ESC Current Rating", "unit": "A",
         "type": "number", "help": "Optional."},
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number",
         "default": "0"},
    ],
}


def run(inputs):
    try:
        kv = units.positive(inputs, "kv", "", "Motor Kv")
        motor_watts = units.optional(inputs, "motor_watts", "W", 0.0)
        motor_max_current = units.optional(inputs, "motor_max_current", "A", 0.0)
        cells = int(units.positive(inputs, "cells", "", "Cell count", default=4))
        chemistry = inputs.get("chemistry") or "LiPo"
        diameter = units.positive(inputs, "diameter", "m", "Propeller diameter")
        pitch = units.positive(inputs, "pitch", "m", "Propeller pitch")
        load_factor = units.fraction(inputs, "load_factor", 0.85)
        eta_motor = units.fraction(inputs, "motor_eff", 0.80)
        cruise_speed = units.optional(inputs, "cruise_speed", "m/s", 0.0)
        esc_rating = units.optional(inputs, "esc_rating", "A", 0.0)
        altitude = units.optional(inputs, "altitude", "m", 0.0)

        spec = battery.CHEMISTRY[chemistry]
        voltage = battery.nominal_voltage(cells, chemistry)
        full_voltage = cells * spec["full"]

        rpm = propulsion.motor_rpm(kv, voltage, load_factor)
        rpm_full = propulsion.motor_rpm(kv, full_voltage, load_factor)
        unloaded = kv * voltage

        thrust = propulsion.static_thrust(diameter, pitch, rpm, altitude)
        shaft = propulsion.static_shaft_power(diameter, pitch, rpm, altitude)
        electrical = shaft / eta_motor
        current = electrical / voltage
        ct, cp = propulsion.static_coefficients(pitch / diameter)

        tip_speed = math.pi * diameter * rpm / 60.0
        pitch_speed = propulsion.pitch_speed(rpm, pitch)
        pd_ratio = pitch / diameter

        r = report.Report("Motor & Propeller Match")
        r.section("Combination")
        r.value("Motor Kv", kv, "rpm/V", 0)
        r.value("Pack", f"{cells}S {chemistry}")
        r.value("Nominal voltage", voltage, "V", 2)
        r.value("Charged voltage", full_voltage, "V", 2)
        r.dual("Propeller diameter", diameter, "m", "in", 4)
        r.dual("Propeller pitch", pitch, "m", "in", 4)
        r.value("Pitch/diameter ratio", pd_ratio, "", 3)

        r.section("Rotation")
        r.value("Unloaded RPM (Kv x V)", unloaded, "rpm", 0)
        r.value("Loaded RPM at nominal", rpm, "rpm", 0,
                note=f"{load_factor * 100:.0f}% of unloaded")
        r.value("Loaded RPM at full charge", rpm_full, "rpm", 0)
        r.value("Tip speed", tip_speed, "m/s", 1)
        r.value("Tip Mach", tip_speed / 340.3, "", 3)

        r.section("Propeller Coefficients")
        r.value("Thrust coefficient Ct", ct, "", 4)
        r.value("Power coefficient Cp", cp, "", 4)
        r.text("  T = Ct * rho * n^2 * D^4     P = Cp * rho * n^3 * D^5")

        r.section("Static Performance")
        r.value("Static thrust", thrust, "N", 3)
        r.value("  in grams", thrust / G * 1000, "g", 0)
        r.dual("  also", thrust, "N", "lbf", 3)
        r.value("Shaft power", shaft, "W", 1)
        r.value("Electrical power", electrical, "W", 1)
        r.value("Current at nominal voltage", current, "A", 2)
        r.value("Thrust efficiency", thrust / G * 1000 / electrical, "g/W", 2)
        r.value("Pitch speed", pitch_speed, "m/s", 1)
        r.value("  also", units.ms_to_mph(pitch_speed), "mph", 1)

        r.section("Limits")
        issues = 0
        if motor_watts > 0:
            usage = 100.0 * electrical / motor_watts
            r.value("Motor rating", motor_watts, "W", 0)
            r.value("Power used", usage, "% of rating", 1)
            if usage > 100:
                r.warn(f"This propeller demands {electrical:.0f} W from a "
                       f"{motor_watts:.0f} W motor. Overloading a motor is the "
                       "usual way to burn one out -- reduce pitch or diameter.")
                issues += 1
            elif usage > 85:
                r.warn("Above 85% of the motor's continuous rating leaves "
                       "little thermal margin for a hot day.")
                issues += 1
            else:
                r.bullet("Comfortably inside the motor's power rating.")

        if motor_max_current > 0:
            r.value("Motor current limit", motor_max_current, "A", 1)
            if current > motor_max_current:
                r.warn(f"Current draw of {current:.1f} A exceeds the motor's "
                       f"{motor_max_current:.1f} A limit.")
                issues += 1

        if esc_rating > 0:
            r.value("ESC rating", esc_rating, "A", 0)
            r.value("ESC headroom", 100.0 * (1 - current / esc_rating), "%", 1)
            if current > esc_rating:
                r.warn("Current exceeds the ESC rating. The ESC will overheat "
                       "and is likely to fail.")
                issues += 1
            elif current > esc_rating * 0.8:
                r.warn("Using more than 80% of the ESC rating; fit a larger "
                       "ESC or improve its cooling.")
                issues += 1

        if tip_speed > 200:
            r.warn(f"Tip speed of {tip_speed:.0f} m/s is approaching the "
                   "transonic range where noise rises sharply and efficiency "
                   "falls. Reduce diameter or Kv.")
            issues += 1
        elif tip_speed > 160:
            r.bullet("Tip speed is high but workable; expect noticeable noise.")

        if pd_ratio > 0.8:
            r.warn("Pitch/diameter above 0.8 is outside the range this model "
                   "covers well. Treat the thrust figure as indicative.")
        elif pd_ratio < 0.3:
            r.bullet("Low pitch: high static thrust, low top speed. Suits "
                     "multirotors and slow flyers.")

        if cruise_speed > 0:
            r.section("Cruise Match")
            ratio = cruise_speed / pitch_speed if pitch_speed > 0 else 0
            r.dual("Intended cruise", cruise_speed, "m/s", "mph", 2)
            r.value("Cruise / pitch speed", ratio, "", 3)
            advance = propulsion.advance_ratio(cruise_speed, rpm, diameter)
            r.value("Advance ratio J", advance, "", 3)
            if ratio > 0.9:
                r.warn("Cruise speed is close to or above the pitch speed. The "
                       "propeller unloads and thrust collapses; more pitch is "
                       "needed.")
            elif ratio > 0.75:
                r.bullet("Well matched: cruising at 75-90% of pitch speed is "
                         "the efficient band for a fixed-wing model.")
            elif ratio > 0.5:
                r.bullet("Slightly over-pitched for this cruise speed, which "
                         "leaves headroom for climb and acceleration.")
            else:
                r.bullet("Heavily over-pitched for this cruise speed. Good "
                         "static thrust, but poor cruise efficiency.")

        if issues == 0:
            r.section("Verdict")
            r.bullet("No limits exceeded. This combination looks workable.")

        r.section("Prop Comparison at This Kv and Pack")
        rows = []
        for d_in, p_in in ((diameter / 0.0254, pitch / 0.0254 - 2),
                           (diameter / 0.0254, pitch / 0.0254),
                           (diameter / 0.0254, pitch / 0.0254 + 2),
                           (diameter / 0.0254 - 1, pitch / 0.0254),
                           (diameter / 0.0254 + 1, pitch / 0.0254)):
            if d_in <= 0 or p_in <= 0:
                continue
            d, p = d_in * 0.0254, p_in * 0.0254
            t = propulsion.static_thrust(d, p, rpm, altitude)
            w = propulsion.static_shaft_power(d, p, rpm, altitude) / eta_motor
            marker = "<-- chosen" if (abs(d - diameter) < 1e-9
                                      and abs(p - pitch) < 1e-9) else ""
            rows.append([f"{d_in:.0f}x{p_in:.1f}", f"{t / G * 1000:.0f}",
                         f"{w:.0f}", f"{w / voltage:.1f}",
                         f"{t / G * 1000 / w:.2f}", marker])
        r.table(["Prop", "Thrust g", "Watts", "Amps", "g/W", ""], rows)

        figures = []
        if plotting.available():
            try:
                rpms, thrusts, powers = [], [], []
                for i in range(1, 26):
                    fraction = i / 25.0
                    rpm_i = rpm * fraction
                    rpms.append(rpm_i)
                    thrusts.append(propulsion.static_thrust(
                        diameter, pitch, rpm_i, altitude) / G * 1000)
                    powers.append(propulsion.static_shaft_power(
                        diameter, pitch, rpm_i, altitude) / eta_motor)
                figures.append(plotting.line_chart(
                    "Thrust vs RPM", "RPM", "Static thrust (g)",
                    [("Thrust", rpms, thrusts)],
                    markers=[(f"Full throttle {thrust / G * 1000:.0f} g",
                              rpm, thrust / G * 1000)]))
                figures.append(plotting.line_chart(
                    "Electrical Power vs RPM", "RPM", "Power (W)",
                    [("Power", rpms, powers)],
                    markers=[(f"{electrical:.0f} W", rpm, electrical)]))
            except Exception:
                r.note("Charts could not be generated.")

        return report.result(r, outputs={
            "Static Thrust": {"value": thrust, "unit": "N"},
            "Loaded RPM": {"value": rpm, "unit": "rpm"},
            "Motor Current": {"value": current, "unit": "A"},
            "Electrical Power": {"value": electrical, "unit": "W"},
            "Pitch Speed": {"value": pitch_speed, "unit": "m/s"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
