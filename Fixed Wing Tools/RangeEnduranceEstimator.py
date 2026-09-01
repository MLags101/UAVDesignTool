"""
Electric Range and Endurance

Rebuilt from the earlier version, which had three weaknesses:

* Only propeller efficiency was applied. The motor, ESC and wiring together
  cost another 20-25%, so ignoring them overstated endurance badly.
* A single fixed Cl/Cd pair was used instead of a drag polar, so the tool could
  not find the speeds that actually maximise range or endurance.
* Range was taken as cruise speed times endurance, which is the best-endurance
  speed, not the best-range speed. They differ by about 32%.

Best endurance occurs at minimum power (CL = sqrt(3*CD0/k)); best range occurs
at minimum drag (CL = sqrt(CD0/k)), which is faster.
"""

import math

from uavlib import aero, atmosphere, battery, plotting, propulsion, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Electric Range & Endurance",
    "category": "Fixed Wing / Performance",
    "description": (
        "Flight time and distance from the drag polar and the full electrical "
        "efficiency chain. Reports best-endurance and best-range speeds "
        "separately, with a climb allowance and a usable-capacity reserve."
    ),
    "inputs": [
        {"key": "mass", "label": "Total Mass", "unit": "kg", "type": "number"},
        {"key": "wing_area", "label": "Wing Area (S)", "unit": "m^2", "type": "number"},
        {"key": "span", "label": "Wing Span (b)", "unit": "m", "type": "number"},
        {"key": "cd0", "label": "Parasite Drag (CD0)", "type": "number",
         "default": "0.035", "help": "From the Drag Buildup tool."},
        {"key": "cl_max", "label": "Max Lift Coefficient", "type": "number",
         "default": "1.2",
         "help": "Used to check the optimum speeds are actually flyable."},
        {"key": "altitude", "label": "Cruise Altitude", "unit": "m",
         "type": "number", "default": "0"},
        {"key": "cells", "label": "Battery Cells (S)", "type": "number", "default": "3"},
        {"key": "chemistry", "label": "Chemistry", "type": "choice",
         "choices": ["LiPo", "Li-ion", "LiHV", "LiFePO4", "NiMH"], "default": "LiPo"},
        {"key": "capacity", "label": "Battery Capacity", "unit": "Ah",
         "type": "number", "help": "Accepts mAh, e.g. '2200 mAh'."},
        {"key": "depth_of_discharge", "label": "Usable Capacity", "unit": "%",
         "type": "number", "default": "80"},
        {"key": "prop_eff", "label": "Propeller Efficiency", "type": "number",
         "default": "0.70"},
        {"key": "motor_eff", "label": "Motor Efficiency", "type": "number",
         "default": "0.80"},
        {"key": "esc_eff", "label": "ESC Efficiency", "type": "number",
         "default": "0.95"},
        {"key": "avionics_power", "label": "Avionics / Payload Draw", "unit": "W",
         "type": "number", "default": "5",
         "help": "Receiver, FPV transmitter, camera, autopilot."},
        {"key": "climb_altitude", "label": "Climb Height", "unit": "m",
         "type": "number", "default": "100",
         "help": "Energy spent climbing is unavailable for cruise."},
        {"key": "cruise_speed", "label": "Chosen Cruise Speed", "unit": "m/s",
         "type": "number", "help": "Optional: compare against the optimum speeds."},
    ],
}


def run(inputs):
    try:
        mass = units.positive(inputs, "mass", "kg", "Mass")
        wing_area = units.positive(inputs, "wing_area", "m^2", "Wing area")
        span = units.positive(inputs, "span", "m", "Span")
        cd0 = units.positive(inputs, "cd0", "", "CD0", default=0.035)
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        cells = int(units.positive(inputs, "cells", "", "Cell count", default=3))
        chemistry = inputs.get("chemistry") or "LiPo"
        capacity = units.positive(inputs, "capacity", "Ah", "Battery capacity")
        dod = units.fraction(inputs, "depth_of_discharge", 0.80)
        eta_prop = units.fraction(inputs, "prop_eff", 0.70)
        eta_motor = units.fraction(inputs, "motor_eff", 0.80)
        eta_esc = units.fraction(inputs, "esc_eff", 0.95)
        avionics = units.optional(inputs, "avionics_power", "W", 5.0)
        climb_height = units.optional(inputs, "climb_altitude", "m", 100.0)
        chosen_speed = units.optional(inputs, "cruise_speed", "m/s", 0.0)

        weight = mass * G
        aspect_ratio = span ** 2 / wing_area
        oswald = aero.oswald_efficiency(aspect_ratio)
        k = aero.induced_drag_factor(aspect_ratio, oswald)
        chain = eta_prop * eta_motor * eta_esc * 0.98

        voltage = battery.nominal_voltage(cells, chemistry)
        total_wh = battery.pack_energy(voltage, capacity)
        usable_wh = battery.usable_energy(voltage, capacity, dod)

        # Climbing to altitude spends energy that cruise never gets back.
        climb_energy_wh = (weight * climb_height / chain) / 3600.0
        cruise_wh = max(0.0, usable_wh - climb_energy_wh)

        best_ld, cl_best = aero.ld_max(cd0, k)
        v_range = aero.speed_min_drag(mass, wing_area, cd0, k, altitude)
        v_endurance = aero.speed_min_power(mass, wing_area, cd0, k, altitude)

        # The theoretical optimum can fall below the stall, which happens
        # whenever CLmax is less than sqrt(3*CD0/k). The aircraft cannot fly
        # there, so the practical optimum is the approach speed instead.
        cl_max = units.positive(inputs, "cl_max", "", "CLmax", default=1.2)
        v_stall = aero.stall_speed(mass, wing_area, cl_max, altitude)
        v_min_flyable = 1.15 * v_stall
        endurance_limited = v_endurance < v_min_flyable
        range_limited = v_range < v_min_flyable
        if endurance_limited:
            v_endurance = v_min_flyable
        if range_limited:
            v_range = v_min_flyable

        def performance(v):
            """Endurance and range at a speed, accounting for avionics draw."""
            aero_power = aero.power_required(mass, wing_area, v, cd0, k, altitude)
            electrical = aero_power / chain + avionics
            hours = cruise_wh / electrical
            return {
                "speed": v,
                "aero_power": aero_power,
                "electrical": electrical,
                "current": electrical / voltage,
                "minutes": hours * 60.0,
                "range_km": v * hours * 3.6,
            }

        endurance_case = performance(v_endurance)
        range_case = performance(v_range)

        r = report.Report("Range & Endurance")
        r.section("Aircraft")
        r.value("Mass", mass, "kg", 3)
        r.value("Wing area", wing_area, "m^2", 4)
        r.value("Aspect ratio", aspect_ratio, "", 2)
        r.value("Wing loading", weight / wing_area, "N/m^2", 1)
        r.value("CD0", cd0, "", 5)
        r.value("Induced factor k", k, "", 5)
        r.value("Best L/D", best_ld, "", 2, note=f"at CL {cl_best:.2f}")

        r.section("Energy")
        r.value("Pack", f"{cells}S {chemistry}")
        r.value("Nominal voltage", voltage, "V", 2)
        r.value("Capacity", capacity, "Ah", 3)
        r.value("Total energy", total_wh, "Wh", 1)
        r.value("Usable energy", usable_wh, "Wh", 1, note=f"{dod * 100:.0f}% DoD")
        r.value("Climb allowance", climb_energy_wh, "Wh", 2,
                note=f"to {climb_height:g} m")
        r.value("Energy for cruise", cruise_wh, "Wh", 1)
        r.value("Estimated pack mass", battery.mass_estimate(voltage, capacity,
                                                             chemistry), "kg", 3)

        r.section("Efficiency Chain")
        r.table(["Stage", "Efficiency"], [
            ["Propeller", f"{eta_prop * 100:.0f}%"],
            ["Motor", f"{eta_motor * 100:.0f}%"],
            ["ESC", f"{eta_esc * 100:.0f}%"],
            ["Wiring", "98%"],
            ["Overall", f"{chain * 100:.1f}%"],
        ])
        r.text("  Propeller efficiency alone would suggest "
               f"{eta_prop * 100:.0f}%; the full chain is {chain * 100:.1f}%.")

        r.section("Optimum Speeds")
        rows = []
        for label, case in (("Best endurance", endurance_case),
                            ("Best range", range_case)):
            rows.append([label, f"{case['speed']:.2f}",
                         f"{units.ms_to_mph(case['speed']):.1f}",
                         f"{case['electrical']:.0f}", f"{case['current']:.1f}",
                         f"{case['minutes']:.1f}", f"{case['range_km']:.2f}"])
        r.table(["Condition", "V m/s", "V mph", "Watts", "Amps", "Minutes", "km"],
                rows)
        r.blank()
        r.value("Max endurance", endurance_case["minutes"], "minutes", 1)
        r.value("Max range", range_case["range_km"], "km", 2)
        r.dual("Stall speed", v_stall, "m/s", "mph", 2)

        if endurance_limited or range_limited:
            r.blank()
            r.warn("The theoretical optimum speed is below this wing's stall "
                   "speed, so it is not reachable. The figures above use "
                   f"1.15 Vs ({v_min_flyable:.2f} m/s) instead.")
            r.bullet("This happens when the wing loading is high relative to "
                     "CLmax. A larger wing, more camber or flaps would let the "
                     "aircraft actually reach its minimum-power condition.")
        else:
            r.text(f"  Best range is {v_range / v_endurance:.2f}x the best-endurance")
            r.text("  speed. Flying for maximum time and maximum distance are")
            r.text("  different problems with different answers.")

        if chosen_speed > 0:
            case = performance(chosen_speed)
            r.section("At Your Chosen Speed")
            r.dual("Cruise speed", chosen_speed, "m/s", "mph", 2)
            r.value("Aerodynamic power", case["aero_power"], "W", 1)
            r.value("Electrical power", case["electrical"], "W", 1)
            r.value("Current draw", case["current"], "A", 2)
            r.value("Endurance", case["minutes"], "minutes", 1)
            r.value("Range", case["range_km"], "km", 2)
            r.value("C rate", battery.c_rate(case["current"], capacity), "C", 1)

            sag = battery.voltage_under_load(cells, capacity, case["current"],
                                             chemistry)
            r.value("Voltage under load", sag["loaded"], "V", 2,
                    note=f"sag {sag['sag_percent']:.1f}%")
            if sag["per_cell_loaded"] < 3.5:
                r.warn("Cell voltage under load is below 3.5 V. The pack is "
                       "working hard; expect reduced capacity and cell wear.")

            loss = 100.0 * (1.0 - case["minutes"] / endurance_case["minutes"])
            if loss > 5:
                r.bullet(f"This speed costs {loss:.0f}% of the maximum "
                         f"endurance. Slowing to {v_endurance:.1f} m/s would "
                         f"give {endurance_case['minutes']:.1f} minutes.")

        r.section("Notes")
        r.bullet("Wind changes the range answer entirely: into a headwind, fly "
                 "faster than best-range speed; downwind, slower.")
        r.bullet("These figures assume level cruise. Aerobatics, repeated "
                 "climbs and go-arounds will cut them substantially.")
        if endurance_case["minutes"] < 8:
            r.warn("Under 8 minutes leaves little reserve for a circuit and "
                   "approach. Consider a larger pack or a lighter airframe.")

        figures = []
        if plotting.available():
            try:
                speeds, powers, ranges = [], [], []
                v_lo = max(3.0, v_endurance * 0.5)
                v_hi = v_range * 2.2
                for i in range(60):
                    v = v_lo + (v_hi - v_lo) * i / 59
                    case = performance(v)
                    speeds.append(v)
                    powers.append(case["electrical"])
                    ranges.append(case["range_km"])
                figures.append(plotting.line_chart(
                    "Power Required vs Airspeed", "Airspeed (m/s)",
                    "Electrical power (W)", [("Power", speeds, powers)],
                    markers=[(f"Best endurance {v_endurance:.1f} m/s",
                              v_endurance, endurance_case["electrical"]),
                             (f"Best range {v_range:.1f} m/s",
                              v_range, range_case["electrical"])]))
                figures.append(plotting.line_chart(
                    "Range vs Airspeed", "Airspeed (m/s)", "Range (km)",
                    [("Range", speeds, ranges)],
                    markers=[(f"Max {range_case['range_km']:.1f} km",
                              v_range, range_case["range_km"])]))
            except Exception:
                r.note("Charts could not be generated.")

        return report.result(r, outputs={
            "Max Endurance": {"value": endurance_case["minutes"], "unit": "min"},
            "Max Range": {"value": range_case["range_km"], "unit": "km"},
            "Best Endurance Speed": {"value": v_endurance, "unit": "m/s"},
            "Best Range Speed": {"value": v_range, "unit": "m/s"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
