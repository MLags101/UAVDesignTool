"""
Forward Flight Power and Range

A multirotor is not a hovering machine that happens to move: its power actually
falls as it starts moving forward, because the rotors gain an inflow and need
less induced power. Power reaches a minimum somewhere around 8-14 m/s for a
typical airframe, then climbs again as airframe drag takes over.

That minimum is what turns a 20-minute hover into a useful survey range, and it
is invisible to a hover-only endurance calculation.
"""

from uavlib import battery, geometry, plotting, propulsion, report, units
from uavlib import atmosphere
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Forward Flight Power & Range",
    "category": "Multirotor / Performance",
    "description": (
        "Power against airspeed for a multirotor, giving the best-endurance "
        "and best-range cruise speeds and the distance achievable. Includes "
        "the induced, parasite and profile power components separately."
    ),
    "inputs": [
        {"key": "layout", "label": "Frame Layout", "type": "choice",
         "choices": list(geometry.LAYOUTS), "default": "Quadcopter X"},
        {"key": "mass", "label": "All-Up Mass", "unit": "kg", "type": "number"},
        {"key": "rotor_diameter", "label": "Rotor Diameter", "unit": "m",
         "type": "number", "help": "Accepts '10 in' or '10x4.7'."},
        {"key": "flat_plate_area", "label": "Equivalent Flat Plate Area",
         "unit": "m^2", "type": "number", "default": "0.01",
         "help": "Airframe drag area (CD x frontal area). Roughly 0.004 for a "
                 "clean racer, 0.010 for a camera quad, 0.025 for a large "
                 "hexacopter with exposed payload."},
        {"key": "figure_of_merit", "label": "Figure of Merit", "type": "number",
         "default": "0.65", "min": 0.3, "max": 0.85},
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number",
         "default": "0"},
        {"key": "cells", "label": "Battery Cells (S)", "type": "number",
         "default": "4"},
        {"key": "capacity", "label": "Battery Capacity", "unit": "Ah",
         "type": "number", "help": "Accepts mAh."},
        {"key": "depth_of_discharge", "label": "Usable Capacity", "unit": "%",
         "type": "number", "default": "80"},
        {"key": "motor_eff", "label": "Motor Efficiency", "type": "number",
         "default": "0.80"},
        {"key": "esc_eff", "label": "ESC Efficiency", "type": "number",
         "default": "0.95"},
        {"key": "avionics_power", "label": "Avionics / Payload Draw", "unit": "W",
         "type": "number", "default": "8"},
        {"key": "headwind", "label": "Headwind", "unit": "m/s", "type": "number",
         "default": "0", "help": "Reduces ground speed and therefore range."},
    ],
}


def run(inputs):
    try:
        layout_name = inputs.get("layout") or "Quadcopter X"
        frame = geometry.layout(layout_name)
        mass = units.positive(inputs, "mass", "kg", "All-up mass")
        diameter = units.positive(inputs, "rotor_diameter", "m", "Rotor diameter")
        flat_plate = units.positive(inputs, "flat_plate_area", "m^2",
                                    "Flat plate area", default=0.01)
        fm = units.optional(inputs, "figure_of_merit", "", 0.65) or 0.65
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        cells = int(units.optional(inputs, "cells", "", 4) or 4)
        capacity = units.positive(inputs, "capacity", "Ah", "Battery capacity")
        dod = units.fraction(inputs, "depth_of_discharge", 0.80)
        eta_motor = units.fraction(inputs, "motor_eff", 0.80)
        eta_esc = units.fraction(inputs, "esc_eff", 0.95)
        avionics = units.optional(inputs, "avionics_power", "W", 8.0)
        headwind = units.optional(inputs, "headwind", "m/s", 0.0)

        voltage = battery.nominal_voltage(cells, "LiPo")
        usable_wh = battery.usable_energy(voltage, capacity, dod)
        # Coaxial pairs share a disk, so momentum theory sees arms, not motors.
        disks = geometry.disk_count(frame)
        coaxial_factor = (1.0 / propulsion.COAXIAL_EFFICIENCY
                          if frame.coaxial else 1.0)

        def electrical_at(v):
            shaft = propulsion.forward_flight_power(
                mass, v, diameter, disks, flat_plate, fm, altitude)
            if coaxial_factor != 1.0:
                shaft = {key: value * coaxial_factor if key != "induced_velocity"
                         else value for key, value in shaft.items()}
            total = propulsion.electrical_power(shaft["total"], eta_motor,
                                                eta_esc) + avionics
            return shaft, total

        hover_shaft, hover_power = electrical_at(0.0)

        # Sweep speed to find the two optima. Ground speed drives range, so a
        # headwind shifts the best-range speed upward.
        best_endurance_v, best_endurance_p = 0.0, hover_power
        best_range_v, best_range_km = 0.0, 0.0
        samples = []
        for i in range(0, 351):
            v = i / 10.0
            _, power = electrical_at(v)
            hours = usable_wh / power
            ground_speed = max(0.0, v - headwind)
            distance = ground_speed * hours * 3.6
            samples.append((v, power, distance))
            if power < best_endurance_p:
                best_endurance_p, best_endurance_v = power, v
            if distance > best_range_km:
                best_range_km, best_range_v = distance, v

        hover_minutes = usable_wh / hover_power * 60.0
        endurance_minutes = usable_wh / best_endurance_p * 60.0

        r = report.Report("Forward Flight Performance")
        r.section("Airframe")
        r.value("Layout", f"{layout_name} ({frame.motors} motors)")
        r.dual("All-up mass", mass, "kg", "lb", 3)
        r.dual("Rotor diameter", diameter, "m", "in", 4)
        r.value("Flat plate area", flat_plate, "m^2", 4)
        r.value("Altitude", altitude, "m", 0)
        r.value("Usable energy", usable_wh, "Wh", 1)
        if headwind:
            r.dual("Headwind", headwind, "m/s", "mph", 2)

        r.section("Hover")
        r.value("Hover power (electrical)", hover_power, "W", 1)
        r.value("Hover current", hover_power / voltage, "A", 2)
        r.value("Hover endurance", hover_minutes, "minutes", 1)
        r.value("Hover efficiency",
                propulsion.hover_efficiency(mass * G, hover_power), "g/W", 2)

        r.section("Optimum Cruise")
        _, endurance_power = electrical_at(best_endurance_v)
        _, range_power = electrical_at(best_range_v)
        r.dual("Best-endurance speed", best_endurance_v, "m/s", "mph", 2)
        r.value("  power there", endurance_power, "W", 1)
        r.value("  endurance", endurance_minutes, "minutes", 1)
        r.value("  power saving vs hover",
                100.0 * (1 - endurance_power / hover_power), "%", 1)
        r.blank()
        r.dual("Best-range speed", best_range_v, "m/s", "mph", 2)
        r.value("  power there", range_power, "W", 1)
        r.value("  range", best_range_km, "km", 2)
        if headwind:
            r.dual("  ground speed", max(0.0, best_range_v - headwind),
                   "m/s", "mph", 2)

        r.section("Power Breakdown")
        rows = []
        for v in (0, 2, 5, 8, 12, 16, 20, 25):
            shaft, total = electrical_at(float(v))
            rows.append([f"{v}", f"{shaft['induced']:.0f}",
                         f"{shaft['parasite']:.0f}", f"{shaft['profile']:.0f}",
                         f"{total:.0f}", f"{total / voltage:.1f}"])
        r.table(["V m/s", "Induced W", "Parasite W", "Profile W", "Total W", "Amps"],
                rows)
        r.text("  Induced power falls with speed as the rotors gain inflow;")
        r.text("  parasite power grows as the cube of speed. The minimum")
        r.text("  between them is the efficient cruise.")

        r.section("Assessment")
        saving = 100.0 * (1 - endurance_power / hover_power)
        r.bullet(f"Cruising at {best_endurance_v:.1f} m/s uses {saving:.0f}% "
                 f"less power than hovering: {endurance_minutes:.1f} minutes "
                 f"against {hover_minutes:.1f}.")
        r.bullet(f"Maximum range is {best_range_km:.1f} km at "
                 f"{best_range_v:.1f} m/s, which is faster than the "
                 "best-endurance speed.")
        if headwind > 0:
            no_wind = max(s[2] for s in samples if True)
            r.bullet(f"The {headwind:g} m/s headwind is already accounted for "
                     "in the range figure; fly faster into wind than you would "
                     "in still air.")
        if best_range_v > 22:
            r.warn("The best-range speed is high enough that rotor advance "
                   "ratio effects this model ignores will start to matter. "
                   "Treat speeds above about 22 m/s as indicative.")

        figures = []
        if plotting.available():
            try:
                speeds = [s[0] for s in samples]
                powers = [s[1] for s in samples]
                distances = [s[2] for s in samples]
                figures.append(plotting.line_chart(
                    "Power vs Airspeed", "Airspeed (m/s)", "Electrical power (W)",
                    [("Total power", speeds, powers)],
                    markers=[(f"Best endurance {best_endurance_v:.1f} m/s",
                              best_endurance_v, endurance_power),
                             ("Hover", 0.0, hover_power)]))
                figures.append(plotting.line_chart(
                    "Range vs Airspeed", "Airspeed (m/s)", "Range (km)",
                    [("Range", speeds, distances)],
                    markers=[(f"Max {best_range_km:.1f} km", best_range_v,
                              best_range_km)]))
                induced, parasite, profile = [], [], []
                for v in speeds:
                    shaft, _ = electrical_at(v)
                    induced.append(shaft["induced"])
                    parasite.append(shaft["parasite"])
                    profile.append(shaft["profile"])
                figures.append(plotting.line_chart(
                    "Power Components", "Airspeed (m/s)", "Shaft power (W)",
                    [("Induced", speeds, induced),
                     ("Parasite", speeds, parasite),
                     ("Profile", speeds, profile)]))
            except Exception:
                r.note("Charts could not be generated.")

        return report.result(r, outputs={
            "Hover Endurance": {"value": hover_minutes, "unit": "min"},
            "Best Cruise Speed": {"value": best_endurance_v, "unit": "m/s"},
            "Max Range": {"value": best_range_km, "unit": "km"},
            "Best Range Speed": {"value": best_range_v, "unit": "m/s"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
