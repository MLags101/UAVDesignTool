"""
Panel Flutter Screening

Thin skin panels between ribs or frames can flutter in supersonic flow.
Piston theory gives the flutter parameter lambda = 2 q a^3 / (beta D); a
2-D simply supported panel flutters above about 512. The tool reports the
margin and the minimum skin thickness at the worst flight condition.
A screen only: piston theory is unconservative below about Mach 1.4.
"""

from uavlib import atmosphere, report, structures, units

TOOL_METADATA = {
    "name": "Panel Flutter Screening",
    "category": "Supersonic / Structures",
    "description": (
        "Piston-theory panel flutter parameter, margin and minimum skin thickness for a "
        "skin panel at a supersonic flight condition."
    ),
    "inputs": [
        {"key": "mach", "label": "Mach Number", "type": "number", "default": "1.6"},
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number", "default": "11000"},
        {"key": "panel_length", "label": "Panel Length (streamwise)", "unit": "m",
         "type": "number", "default": "0.15"},
        {"key": "thickness", "label": "Skin Thickness", "unit": "m", "type": "number",
         "default": "0.8 mm"},
        {"key": "modulus", "label": "Skin Modulus", "unit": "Pa", "type": "number",
         "default": "50e9", "help": "Quasi-isotropic carbon ~50 GPa, aluminium 70 GPa."},
        {"key": "poisson", "label": "Poisson's Ratio", "type": "number", "default": "0.3"},
        {"key": "edges", "label": "Edge Support", "type": "choice",
         "choices": ["Simply supported", "Clamped"], "default": "Simply supported"},
    ],
}


def run(inputs):
    try:
        mach = units.positive(inputs, "mach", "", "Mach", 1.6)
        if not 1.0 < mach <= 2.0:
            raise ValueError("Panel flutter screening needs Mach between 1 and 2.")
        altitude = units.optional(inputs, "altitude", "m", 11000.0)
        length = units.positive(inputs, "panel_length", "m", "Panel length", 0.15)
        thickness = units.positive(inputs, "thickness", "m", "Thickness", 0.0008)
        modulus = units.positive(inputs, "modulus", "Pa", "Modulus", 50e9)
        poisson = units.optional(inputs, "poisson", "", 0.3)
        # Clamped edges raise the critical value; 636 is the commonly quoted 2-D figure.
        critical = 636.0 if inputs.get("edges") == "Clamped" else structures.PANEL_FLUTTER_CRITICAL

        air = atmosphere.at(altitude)
        q = 0.5 * air.density * (mach * air.sound_speed) ** 2
        result = structures.panel_flutter(mach, q, length, thickness, modulus, poisson, critical)
        r = report.Report("Panel Flutter Screening")
        r.value("Dynamic pressure", q, "Pa", 0)
        r.value("Flutter parameter", result["parameter"], "", 1)
        r.value("Critical value", critical, "", 0)
        r.value("Margin (critical/actual - 1)", result["margin"], "", 3)
        r.value("Minimum thickness", result["minimum_thickness"] * 1000, "mm", 3)
        if result["margin"] < 0:
            r.warn("The panel is predicted to flutter: thicken the skin, add stiffeners or "
                   "shorten the panel.")
        elif result["margin"] < 1:
            r.warn("Less than a factor of two on the flutter parameter; check with a "
                   "detailed analysis.")
        else:
            r.bullet("Comfortable margin at this condition.")
        if mach < 1.4:
            r.warn("Piston theory is unconservative below about Mach 1.4.")
        r.note("Flutter parameter varies as a^3 / t^3: panel length is the strongest lever.")
        return report.result(r, outputs={
            "Panel Flutter Margin": {"value": result["margin"], "unit": ""},
            "Minimum Skin Thickness": {"value": result["minimum_thickness"], "unit": "m"}})
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
