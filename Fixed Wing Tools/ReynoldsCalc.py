"""
Reynolds Number Calculator

Reynolds number decides which aerofoil data is even applicable. Model aircraft
usually operate between 50,000 and 500,000, a range where sections behave very
differently from their full-scale published polars, so the tool reports the
regime and its consequences rather than just the number.

Density and viscosity now follow the standard atmosphere at the given altitude
instead of being fixed at sea level.
"""

from uavlib import atmosphere, report, units

TOOL_METADATA = {
    "name": "Reynolds Number Calculator",
    "category": "Fixed Wing / Aerodynamics",
    "description": (
        "Reynolds number at altitude, with the low-Reynolds guidance that "
        "matters for models. Reports Re at the root, mean and tip chords so a "
        "tapered wing can be checked where it is most vulnerable."
    ),
    "inputs": [
        {"key": "velocity", "label": "Airspeed", "unit": "m/s", "type": "number"},
        {"key": "chord", "label": "Reference Chord (MAC)", "unit": "m", "type": "number"},
        {"key": "root_chord", "label": "Root Chord", "unit": "m", "type": "number",
         "help": "Optional. Fill in with the tip chord to check a tapered wing."},
        {"key": "tip_chord", "label": "Tip Chord", "unit": "m", "type": "number",
         "help": "Optional. The tip stalls first, and it is where Re is lowest."},
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number",
         "default": "0"},
        {"key": "stall_speed", "label": "Stall Speed", "unit": "m/s", "type": "number",
         "help": "Optional. Checks Re in the landing case, the worst case."},
    ],
}


def run(inputs):
    try:
        velocity = units.positive(inputs, "velocity", "m/s", "Airspeed")
        chord = units.positive(inputs, "chord", "m", "Reference chord")
        root_chord = units.optional(inputs, "root_chord", "m", 0.0)
        tip_chord = units.optional(inputs, "tip_chord", "m", 0.0)
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        stall_speed = units.optional(inputs, "stall_speed", "m/s", 0.0)

        air = atmosphere.at(altitude)
        re = atmosphere.reynolds(velocity, chord, altitude)

        r = report.Report("Reynolds Number")
        r.section("Air Properties")
        r.value("Altitude", altitude, "m", 0)
        r.value("Temperature", air.temperature - 273.15, "degC", 1)
        r.value("Density", air.density, "kg/m^3", 4)
        r.value("Dynamic viscosity", air.viscosity, "Pa.s", 8)
        r.value("Kinematic viscosity", air.kinematic_viscosity, "m^2/s", 8)
        r.value("Speed of sound", air.sound_speed, "m/s", 1)
        r.value("Mach number", velocity / air.sound_speed, "", 4)

        r.section("Reynolds Number")
        r.value("Airspeed", velocity, "m/s", 2)
        r.value("Reference chord", chord, "m", 4)
        r.value("Re at reference chord", re, "", 0)

        stations = []
        if root_chord > 0:
            stations.append(("Root", root_chord, velocity))
        stations.append(("MAC", chord, velocity))
        if tip_chord > 0:
            stations.append(("Tip", tip_chord, velocity))
        if stall_speed > 0:
            stations.append(("MAC at stall", chord, stall_speed))
            if tip_chord > 0:
                stations.append(("Tip at stall", tip_chord, stall_speed))

        if len(stations) > 1:
            r.blank()
            rows = []
            for label, c, v in stations:
                value = atmosphere.reynolds(v, c, altitude)
                rows.append([label, f"{c:.4f}", f"{v:.1f}", f"{value:,.0f}"])
            r.table(["Station", "Chord m", "V m/s", "Re"], rows)

        r.section("Flow Regime")
        r.text(f"  {atmosphere.reynolds_note(re)}")

        lowest_label, lowest_re = None, None
        for label, c, v in stations:
            value = atmosphere.reynolds(v, c, altitude)
            if lowest_re is None or value < lowest_re:
                lowest_label, lowest_re = label, value

        if lowest_re is not None and lowest_re < re * 0.95:
            r.blank()
            r.value(f"Lowest Re ({lowest_label})", lowest_re, "", 0)
            r.text(f"  {atmosphere.reynolds_note(lowest_re)}")

        if lowest_re is not None and lowest_re < 70_000:
            r.warn("Part of this wing operates below Re 70,000. Expect a large "
                   "drag rise and reduced CLmax there. On a tapered wing this "
                   "makes the tip stall first, which drops a wing at low speed.")
            r.bullet("Fixes: reduce taper, add washout, use a turbulator strip, "
                     "or pick a section designed for low Re.")
        elif lowest_re is not None and lowest_re < 200_000:
            r.bullet("Use aerofoil polars measured at this Reynolds number. "
                     "Full-scale data will flatter the section considerably.")

        r.section("Reference")
        r.table(["Regime", "Re", "Character"], [
            ["Indoor / micro", "< 50k", "Very difficult; thin cambered plates win"],
            ["Small park flyer", "50-100k", "Bubble-dominated, section critical"],
            ["Typical RC sport", "100-500k", "Well-served by low-Re sections"],
            ["Large RC / UAV", "500k-1M", "Approaching full-scale behaviour"],
            ["Full scale light", "> 1M", "Published polars broadly apply"],
        ])

        return report.result(r, outputs={
            "Reynolds Number": {"value": re},
            "Cruise Airspeed": {"value": velocity, "unit": "m/s"},
        })

    except units.UnitError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
