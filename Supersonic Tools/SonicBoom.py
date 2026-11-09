"""
Sonic Boom

Ground overpressure and signature duration of the N-wave in steady level
flight, from the aircraft's equivalent area (volume plus lift) through
Whitham's F-function -- the theory behind Carlson's simplified method
(NASA TP-1122). Also reports the cut-off Mach below which the boom refracts
away before reaching the ground. Reported for information: there is no
overland supersonic requirement in this tool.
"""

from uavlib import jet_inputs, plotting, report, sonic_boom, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Sonic Boom",
    "category": "Supersonic / Environment",
    "description": (
        "N-wave ground overpressure and duration from the volume-plus-lift equivalent "
        "area (Whitham / Carlson), with the Mach cut-off check."
    ),
    "inputs": [
        {"key": "mass", "label": "Aircraft Mass", "unit": "kg", "type": "number", "default": "105"},
        {"key": "mach", "label": "Mach Number", "type": "number", "default": "1.6"},
        {"key": "altitude", "label": "Flight Altitude", "unit": "m", "type": "number",
         "default": "11000"},
        {"key": "reflection", "label": "Ground Reflection Factor", "type": "number",
         "default": "1.9", "help": "2.0 rigid ground; 1.8-1.9 typical terrain."},
    ] + jet_inputs.GEOMETRY_INPUTS,
}


def run(inputs):
    try:
        config = jet_inputs.configuration(inputs)
        mass = units.positive(inputs, "mass", "kg", "Mass", 105.0)
        mach = units.positive(inputs, "mach", "", "Mach", 1.6)
        if not 1.0 < mach <= 2.0:
            raise ValueError("Sonic boom needs Mach between 1 and 2.")
        altitude = units.positive(inputs, "altitude", "m", "Altitude", 11000.0)
        reflection = units.positive(inputs, "reflection", "", "Reflection factor", 1.9)

        boom = sonic_boom.aircraft_boom(config, mass * G, mach, altitude, reflection)
        r = report.Report("Sonic Boom")
        r.value("Mach", mach, "", 2)
        r.value("Altitude", altitude, "m", 0)
        r.value("Weight", mass * G, "N", 1)
        r.value("Cut-off Mach", boom["cutoff_mach"], "", 3)
        outputs = {}
        if not boom["reaches_ground"]:
            r.bullet("Below the cut-off Mach the shock refracts upward and no boom reaches the "
                     "ground (standard atmosphere, no wind).")
            outputs["Ground Overpressure"] = {"value": 0.0, "unit": "Pa"}
        else:
            dp = boom["overpressure"]
            r.section("Ground Signature (N-wave)")
            r.value("Peak overpressure", dp, "Pa", 1)
            r.value("  also", dp / 47.88, "psf", 3)
            r.value("Signature duration", boom["duration"] * 1000, "ms", 1)
            r.value("F-function integral", boom["integral"], "m^0.5", 5)
            if dp < 25:
                r.bullet("Under 25 Pa (0.5 psf): comparable to distant thunder.")
            elif dp < 50:
                r.bullet("25-50 Pa (0.5-1 psf): clearly audible, rarely startling.")
            else:
                r.bullet("Above 50 Pa (1 psf): a noticeable boom; Concorde was about 90-100 Pa.")
            r.bullet("Flying higher lowers the boom roughly as altitude^-3/4; weight and length "
                     "set its strength through the equivalent area.")
            outputs = {"Ground Overpressure": {"value": dp, "unit": "Pa"},
                       "Boom Duration": {"value": boom["duration"], "unit": "s"}}
        r.note("Whitham far-field theory with a geometric-mean pressure correction; winds, "
               "turbulence and focusing during manoeuvres are not modelled.")

        figures = []
        if plotting.available():
            xs, ae = boom["equivalent_area"]
            figures.append(plotting.line_chart("Equivalent Area (volume + lift)", "x (m)",
                                               "A_e (m^2)", [("A_e", xs, ae)]))
        return report.result(r, outputs=outputs, figures=figures)
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
