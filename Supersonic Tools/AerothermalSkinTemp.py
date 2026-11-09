"""
Aerothermal Skin Temperature

At Mach 2 the airframe skin heats towards the recovery temperature -- about
100 C in the stratosphere, enough to soften room-temperature-cure composites
and 3D-printed parts. Reports stagnation, recovery and radiative-equilibrium
skin temperatures, compares them with the material's service limit, and
estimates how long a thin skin takes to soak to temperature.
"""

import math

from uavlib import aerothermal, atmosphere, plotting, report, units

TOOL_METADATA = {
    "name": "Aerothermal Skin Temperature",
    "category": "Supersonic / Structures",
    "description": (
        "Stagnation, recovery and radiative-equilibrium skin temperatures, material "
        "temperature margin and thin-skin soak time at a flight condition."
    ),
    "inputs": [
        {"key": "mach", "label": "Mach Number", "type": "number", "default": "1.8"},
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number", "default": "11000"},
        {"key": "distance", "label": "Distance from Leading Edge", "unit": "m",
         "type": "number", "default": "0.3"},
        {"key": "material", "label": "Skin Material", "type": "choice",
         "choices": list(aerothermal.MATERIALS), "default": "Carbon/epoxy, 120 C cure"},
        {"key": "emissivity", "label": "Surface Emissivity", "type": "number", "default": "0.85"},
        {"key": "skin_thickness", "label": "Skin Thickness", "unit": "m", "type": "number",
         "default": "1.5 mm"},
        {"key": "skin_density", "label": "Skin Density", "unit": "kg/m^3", "type": "number",
         "default": "1550"},
        {"key": "skin_cp", "label": "Skin Specific Heat", "unit": "J/kg/K", "type": "number",
         "default": "900"},
        {"key": "dash_time", "label": "Time at This Condition", "unit": "s", "type": "number",
         "default": "120"},
    ],
}


def run(inputs):
    try:
        mach = units.positive(inputs, "mach", "", "Mach")
        if mach > 2.0:
            raise ValueError("Mach above the Mach 2 model ceiling.")
        altitude = units.optional(inputs, "altitude", "m", 11000.0)
        distance = units.positive(inputs, "distance", "m", "Distance", 0.3)
        material = inputs.get("material") or "Carbon/epoxy, 120 C cure"
        limit = aerothermal.MATERIALS[material]
        emissivity = units.optional(inputs, "emissivity", "", 0.85)
        thickness = units.positive(inputs, "skin_thickness", "m", "Skin thickness", 0.0015)
        density = units.positive(inputs, "skin_density", "", "Skin density", 1550.0)
        cp = units.positive(inputs, "skin_cp", "", "Skin specific heat", 900.0)
        dash = units.optional(inputs, "dash_time", "s", 120.0)

        t = aerothermal.skin_temperature(mach, altitude, distance, emissivity)
        soak = aerothermal.soak_time(t["h"], thickness, density, cp) if t["h"] > 0 else 0.0
        # Lumped heating towards equilibrium from the ambient temperature.
        tau = density * cp * thickness / t["h"] if t["h"] > 0 else math.inf
        ambient = atmosphere.at(altitude).temperature
        after_dash = t["equilibrium"] - (t["equilibrium"] - ambient) * math.exp(-dash / tau)

        def c(k):
            return k - 273.15

        r = report.Report("Aerothermal Skin Temperature")
        r.value("Mach", mach, "", 2)
        r.value("Altitude", altitude, "m", 0)
        r.value("Ambient temperature", c(ambient), "degC", 1)
        r.section("Temperatures")
        r.value("Stagnation (nose, edges)", c(t["stagnation"]), "degC", 1)
        r.value("Recovery (adiabatic skin)", c(t["recovery"]), "degC", 1)
        r.value("Radiative equilibrium skin", c(t["equilibrium"]), "degC", 1)
        r.value("Heat transfer coefficient", t["h"], "W/m^2/K", 1)
        r.section("Material")
        r.value("Material", material)
        r.value("Service limit", c(limit), "degC", 0)
        margin = limit - t["stagnation"]
        r.value("Margin to stagnation temp.", margin, "K", 1)
        r.value("Skin 90% soak time", soak, "s", 0)
        r.value(f"Skin after {dash:g} s", c(after_dash), "degC", 1)
        if t["stagnation"] > limit:
            if after_dash > limit:
                r.warn("The skin exceeds the material's service limit during this exposure.")
            else:
                r.warn("Steady state exceeds the limit; only short dashes are tolerable.")
        else:
            r.bullet("Within the material limit at steady state.")
        r.note("Radiative equilibrium uses Eckert's reference temperature with turbulent flow; "
               "laminar regions run cooler, leading edges reach the stagnation value.")

        figures = []
        if plotting.available():
            machs = [0.5 + 0.05 * i for i in range(31)]
            stag = [c(aerothermal.skin_temperature(m, altitude, distance, emissivity)["stagnation"]) for m in machs]
            eq = [c(aerothermal.skin_temperature(m, altitude, distance, emissivity)["equilibrium"]) for m in machs]
            figures.append(plotting.line_chart(f"Skin Temperature at {altitude:,.0f} m", "Mach",
                                               "Temperature (degC)",
                                               [("Stagnation", machs, stag), ("Skin equilibrium", machs, eq),
                                                ("Material limit", machs, [c(limit)] * len(machs))]))
        return report.result(r, outputs={
            "Stagnation Temperature": {"value": t["stagnation"], "unit": "K"},
            "Skin Equilibrium Temperature": {"value": t["equilibrium"], "unit": "K"},
            "Skin Soak Time": {"value": soak, "unit": "s"}}, figures=figures)
    except (units.UnitError, ValueError, KeyError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
