"""
Hover Endurance Estimator

Rebuilt from the earlier version, which asked the user for "hover power per
motor" -- the one number a designer cannot know in advance and is precisely
what needs calculating. Hover power now comes from momentum theory:

    P_ideal = T^1.5 / sqrt(2 * rho * A)
    P_shaft = P_ideal / FM

with the figure of merit FM covering the real rotor's departure from the ideal.
Voltage sag, motor and ESC losses and avionics draw are all included.
"""

from uavlib import battery, geometry, plotting, propulsion, report, units
from uavlib.atmosphere import G
from uavlib import atmosphere

TOOL_METADATA = {
    "name": "Hover Endurance Estimator",
    "category": "Multirotor / Performance",
    "description": (
        "Hover time from airframe mass and rotor size using momentum theory. "
        "Derives hover power rather than asking for it, and accounts for the "
        "coaxial penalty on over-under layouts."
    ),
    "inputs": [
        {"key": "layout", "label": "Frame Layout", "type": "choice",
         "choices": list(geometry.LAYOUTS), "default": "Quadcopter X"},
        {"key": "mass", "label": "All-Up Mass", "unit": "kg", "type": "number",
         "help": "Including battery and payload."},
        {"key": "rotor_diameter", "label": "Rotor Diameter", "unit": "m",
         "type": "number", "help": "Accepts inches, e.g. '10 in' or '10x4.7'."},
        {"key": "figure_of_merit", "label": "Figure of Merit", "type": "number",
         "default": "0.65", "min": 0.3, "max": 0.85,
         "help": "0.55 cheap plastic props, 0.65 good carbon, 0.75 large "
                 "well-matched rotors."},
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number",
         "default": "0"},
        {"key": "cells", "label": "Battery Cells (S)", "type": "number",
         "default": "4"},
        {"key": "chemistry", "label": "Chemistry", "type": "choice",
         "choices": ["LiPo", "Li-ion", "LiHV", "LiFePO4", "NiMH"], "default": "LiPo"},
        {"key": "capacity", "label": "Battery Capacity", "unit": "Ah",
         "type": "number", "help": "Accepts mAh, e.g. '5000 mAh'."},
        {"key": "depth_of_discharge", "label": "Usable Capacity", "unit": "%",
         "type": "number", "default": "80"},
        {"key": "motor_eff", "label": "Motor Efficiency", "type": "number",
         "default": "0.80"},
        {"key": "esc_eff", "label": "ESC Efficiency", "type": "number",
         "default": "0.95"},
        {"key": "avionics_power", "label": "Avionics / Payload Draw", "unit": "W",
         "type": "number", "default": "8"},
    ],
}


def run(inputs):
    try:
        layout_name = inputs.get("layout") or "Quadcopter X"
        frame = geometry.layout(layout_name)
        mass = units.positive(inputs, "mass", "kg", "All-up mass")
        diameter = units.positive(inputs, "rotor_diameter", "m", "Rotor diameter")
        fm = units.optional(inputs, "figure_of_merit", "", 0.65) or 0.65
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        cells = int(units.positive(inputs, "cells", "", "Cell count", default=4))
        chemistry = inputs.get("chemistry") or "LiPo"
        capacity = units.positive(inputs, "capacity", "Ah", "Battery capacity")
        dod = units.fraction(inputs, "depth_of_discharge", 0.80)
        eta_motor = units.fraction(inputs, "motor_eff", 0.80)
        eta_esc = units.fraction(inputs, "esc_eff", 0.95)
        avionics = units.optional(inputs, "avionics_power", "W", 8.0)

        air = atmosphere.at(altitude)
        weight = mass * G

        # Momentum theory works on swept disk area. A coaxial pair shares one
        # disk, so an X8 has four disks and not eight -- counting eight would
        # make it look more efficient than a quad, which is backwards.
        disks = geometry.disk_count(frame)
        effective_rotors = frame.motors * (1.0 - geometry.COAXIAL_PENALTY) \
            if frame.coaxial else frame.motors
        thrust_per_rotor = weight / effective_rotors
        thrust_per_disk = weight / disks

        shaft_total = propulsion.hover_power(weight, diameter, fm, altitude, disks)
        if frame.coaxial:
            # The lower rotor works in the upper rotor's wash, so the pair needs
            # more shaft power than a single rotor of the same total thrust.
            shaft_total /= propulsion.COAXIAL_EFFICIENCY
        shaft_per_rotor = shaft_total / frame.motors
        electrical = propulsion.electrical_power(shaft_total, eta_motor, eta_esc)
        total_draw = electrical + avionics

        voltage = battery.nominal_voltage(cells, chemistry)
        current = total_draw / voltage
        usable_wh = battery.usable_energy(voltage, capacity, dod)
        minutes = battery.endurance(usable_wh, total_draw)

        sag = battery.voltage_under_load(cells, capacity, current, chemistry)
        disk_loading = propulsion.disk_loading(weight, diameter, disks)
        efficiency = propulsion.hover_efficiency(weight, total_draw)

        r = report.Report("Hover Endurance")
        r.section("Airframe")
        r.value("Layout", f"{layout_name} ({frame.motors} motors, {frame.arms} arms)")
        r.dual("All-up mass", mass, "kg", "lb", 3)
        r.dual("Weight", weight, "N", "lbf", 2)
        r.dual("Rotor diameter", diameter, "m", "in", 4)
        r.value("Altitude", altitude, "m", 0)
        r.value("Air density", air.density, "kg/m^3", 4)
        r.value("Independent rotor disks", disks, "", 0)
        if frame.coaxial:
            r.value("Effective rotors", effective_rotors, "", 2,
                    note=f"{geometry.COAXIAL_PENALTY * 100:.0f}% coaxial penalty")

        r.section("Hover Power (momentum theory)")
        r.value("Thrust per rotor", thrust_per_rotor, "N", 3)
        r.value("  in grams", thrust_per_rotor / G * 1000, "g", 0)
        r.value("Thrust per disk", thrust_per_disk, "N", 3)
        r.value("Disk loading", disk_loading, "N/m^2", 2)
        r.value("Induced velocity", propulsion.induced_velocity(
            thrust_per_disk, diameter, altitude), "m/s", 2)
        r.value("Ideal power (all disks)", propulsion.ideal_hover_power(
            weight, diameter, altitude, disks), "W", 1)
        r.value("Figure of merit", fm, "", 2)
        r.note(propulsion.figure_of_merit_note(fm))
        if frame.coaxial:
            r.value("Coaxial interference factor",
                    propulsion.COAXIAL_EFFICIENCY, "", 2)
        r.value("Shaft power per rotor", shaft_per_rotor, "W", 1)
        r.value("Total shaft power", shaft_total, "W", 1)

        r.section("Electrical")
        r.value("Motor efficiency", eta_motor * 100, "%", 0)
        r.value("ESC efficiency", eta_esc * 100, "%", 0)
        r.value("Propulsion electrical power", electrical, "W", 1)
        r.value("Avionics / payload", avionics, "W", 1)
        r.value("Total draw", total_draw, "W", 1)
        r.value("Current at nominal voltage", current, "A", 2)
        r.value("Current per motor", current / frame.motors, "A", 2)
        r.value("Hover efficiency", efficiency, "g/W", 2)

        r.section("Battery")
        r.value("Pack", f"{cells}S {chemistry}")
        r.value("Nominal voltage", voltage, "V", 2)
        r.value("Capacity", capacity, "Ah", 3)
        r.value("Usable energy", usable_wh, "Wh", 1, note=f"{dod * 100:.0f}% DoD")
        r.value("C rate in hover", battery.c_rate(current, capacity), "C", 1)
        r.value("Voltage under load", sag["loaded"], "V", 2,
                note=f"sag {sag['sag_percent']:.1f}%")
        r.value("Estimated pack mass", battery.mass_estimate(voltage, capacity,
                                                             chemistry), "kg", 3)

        r.section("Result")
        r.value("HOVER ENDURANCE", minutes, "minutes", 1)
        r.value("Nameplate (100% discharge)",
                battery.endurance(battery.pack_energy(voltage, capacity),
                                  total_draw), "minutes", 1)

        r.section("Assessment")
        if efficiency < 6:
            r.warn(f"{efficiency:.1f} g/W is poor. Disk loading is likely too "
                   "high -- larger rotors are the single biggest improvement.")
        elif efficiency < 9:
            r.bullet(f"{efficiency:.1f} g/W is typical of a compact or "
                     "sport-tuned multirotor.")
        elif efficiency < 13:
            r.bullet(f"{efficiency:.1f} g/W is good for a camera platform.")
        else:
            r.bullet(f"{efficiency:.1f} g/W is excellent, typical of a large "
                     "low-disk-loading airframe.")

        if disk_loading > 150:
            r.warn("Disk loading above 150 N/m^2 makes efficient hover very "
                   "hard. Fit larger rotors or reduce mass.")
        if sag["per_cell_loaded"] < 3.6:
            r.warn("Cell voltage already sags below 3.6 V in hover, leaving no "
                   "headroom for manoeuvre. Use a higher-C or larger pack.")
        if minutes < 6:
            r.warn("Under 6 minutes of hover is very short once a landing "
                   "reserve is allowed for.")

        r.blank()
        r.text("  Hover power scales with thrust^1.5 and inversely with rotor")
        r.text("  diameter, so adding mass costs more than proportionally.")
        r.text("  Doubling battery capacity never doubles flight time -- the")
        r.text("  extra pack mass eats into the gain.")

        figures = []
        if plotting.available():
            try:
                # Endurance against battery mass shows the point of diminishing
                # returns, which is the decision this tool exists to support.
                masses, times = [], []
                dry_mass = mass - battery.mass_estimate(voltage, capacity, chemistry)
                for i in range(1, 61):
                    pack_mass = 0.05 * i
                    pack_wh = pack_mass * battery.CHEMISTRY[chemistry]["wh_per_kg"]
                    total_mass = dry_mass + pack_mass
                    if total_mass <= 0:
                        continue
                    shaft = propulsion.hover_power(total_mass * G, diameter, fm,
                                                   altitude, disks)
                    if frame.coaxial:
                        shaft /= propulsion.COAXIAL_EFFICIENCY
                    draw = propulsion.electrical_power(shaft, eta_motor,
                                                       eta_esc) + avionics
                    masses.append(pack_mass)
                    times.append(pack_wh * dod / draw * 60.0)
                peak = max(range(len(times)), key=lambda i: times[i])
                figures.append(plotting.line_chart(
                    "Endurance vs Battery Mass", "Battery mass (kg)",
                    "Hover endurance (min)", [("Endurance", masses, times)],
                    markers=[(f"Optimum {masses[peak]:.2f} kg", masses[peak],
                              times[peak])]))
            except Exception:
                r.note("Chart could not be generated.")

        return report.result(r, outputs={
            "Hover Endurance": {"value": minutes, "unit": "min"},
            "Hover Power": {"value": total_draw, "unit": "W"},
            "Hover Current": {"value": current, "unit": "A"},
            "Disk Loading": {"value": disk_loading, "unit": "N/m^2"},
            "Hover Efficiency": {"value": efficiency, "unit": "g/W"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
