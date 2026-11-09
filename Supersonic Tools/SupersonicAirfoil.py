"""
Supersonic Airfoil

Lift and wave drag of thin supersonic sections by Ackeret linear theory, with
the exact shock-expansion solution for a diamond section as a check. Shows why
supersonic wings are thin: thickness wave drag grows with (t/c)^2 and does not
depend on lift.
"""

import math

from uavlib import plotting, report, supersonic, units

TOOL_METADATA = {
    "name": "Supersonic Airfoil",
    "category": "Supersonic / Aerodynamics",
    "description": (
        "Lift, wave drag and L/D of diamond and biconvex sections by linear theory, "
        "checked against exact shock-expansion theory."
    ),
    "inputs": [
        {"key": "mach", "label": "Mach Number", "type": "number", "default": "1.6"},
        {"key": "alpha", "label": "Angle of Attack", "unit": "deg", "type": "number",
         "default": "3"},
        {"key": "thickness_ratio", "label": "Thickness Ratio (t/c)", "type": "number",
         "default": "0.04"},
        {"key": "section", "label": "Section", "type": "choice",
         "choices": ["Biconvex", "Diamond"], "default": "Biconvex"},
        {"key": "cf", "label": "Skin Friction Coefficient (both sides)", "type": "number",
         "default": "0.005", "help": "Adds viscous drag to the inviscid result for L/D."},
    ],
}


def run(inputs):
    try:
        mach = units.positive(inputs, "mach", "", "Mach number")
        if mach <= 1.05:
            raise ValueError("Use Mach above 1.05; linear supersonic theory fails near Mach 1.")
        alpha = units.optional(inputs, "alpha", "deg", 3.0)
        tc = units.positive(inputs, "thickness_ratio", "", "Thickness ratio", 0.04)
        section = (inputs.get("section") or "Biconvex").lower()
        cf = units.optional(inputs, "cf", "", 0.005)

        linear = supersonic.airfoil_linear(mach, alpha, tc, section)
        r = report.Report("Supersonic Airfoil")
        r.value("Mach", mach, "", 3)
        r.value("Angle of attack", alpha, "deg", 2)
        r.value("t/c", tc, "", 4)
        r.section("Linear (Ackeret) Theory")
        r.value("Lift slope", linear["cl_alpha_per_rad"], "/rad", 3)
        r.value("cl", linear["cl"], "", 4)
        r.value("cd wave, lift", linear["cd_lift"], "", 5)
        r.value("cd wave, thickness", linear["cd_thickness"], "", 5)
        cd_total = linear["cd"] + cf
        r.value("cd total incl. friction", cd_total, "", 5)
        r.value("L/D", linear["cl"] / cd_total if cd_total else 0.0, "", 2)
        r.value("Centre of pressure", 0.5, "x/c", 2)

        if section == "diamond":
            exact = supersonic.diamond_shock_expansion(mach, alpha, tc)
            r.section("Shock-Expansion (exact inviscid)")
            r.value("cl", exact["cl"], "", 4)
            r.value("cd wave", exact["cd"], "", 5)
            if linear["cl"]:
                r.value("Linear-theory cl error", (linear["cl"] / exact["cl"] - 1) * 100, "%", 2)
            r.table(["Panel", "Cp"], [[name, f"{cp:.4f}"] for name, cp in zip(
                ["Upper front", "Upper rear", "Lower front", "Lower rear"], exact["cp_panels"])])

        # Best L/D: cd = cf + K_t tc^2/beta + 4 a^2/beta, cl = 4a/beta.
        beta = supersonic.beta(mach)
        cd0 = cf + supersonic.THICKNESS_FACTOR[section] * tc ** 2 / beta
        alpha_best = math.sqrt(cd0 * beta / 4.0)
        ld_best = (4 * alpha_best / beta) / (2 * cd0)
        r.section("Optimum")
        r.value("Best L/D", ld_best, "", 2)
        r.value("  at angle of attack", math.degrees(alpha_best), "deg", 2)
        r.bullet("Halving t/c quarters the thickness wave drag; L/D rises until friction dominates.")

        figures = []
        if plotting.available():
            alphas = [i * 0.25 for i in range(0, 41)]
            cds = [supersonic.airfoil_linear(mach, a, tc, section)["cd"] + cf for a in alphas]
            cls = [supersonic.airfoil_linear(mach, a, tc, section)["cl"] for a in alphas]
            series = [("Linear theory", cds, cls)]
            if section == "diamond":
                series.append(("Shock-expansion",
                               [supersonic.diamond_shock_expansion(mach, a, tc)["cd"] + cf for a in alphas],
                               [supersonic.diamond_shock_expansion(mach, a, tc)["cl"] for a in alphas]))
            figures.append(plotting.line_chart(f"Drag Polar, Mach {mach:g}", "cd", "cl", series))
        return report.result(r, outputs={
            "Section cl": {"value": linear["cl"], "unit": ""},
            "Section cd": {"value": cd_total, "unit": ""},
            "Section Best L/D": {"value": ld_best, "unit": ""}}, figures=figures)
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
