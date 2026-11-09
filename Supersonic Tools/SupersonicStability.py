"""
Supersonic Static Stability

Longitudinal neutral point and static margin, and directional stability
C_n_beta, from Mach 0.3 to 2. The aerodynamic centre moves aft through Mach 1
(the margin grows, and with it trim drag), while the vertical tail's lift
slope falls as 1/beta and directional stability can vanish near Mach 2.
"""

import math

from uavlib import jet_inputs, plotting, report, supersonic, units

TOOL_METADATA = {
    "name": "Supersonic Static Stability",
    "category": "Supersonic / Stability",
    "description": (
        "Neutral point, static margin and directional stability C_n_beta versus Mach, "
        "including the supersonic aerodynamic-centre shift and fin effectiveness loss."
    ),
    "inputs": [
        {"key": "cg", "label": "CG Position", "unit": "x/MAC", "type": "number", "default": "0.15",
         "help": "Fraction of the wing MAC aft of its leading edge."},
        {"key": "ac_supersonic", "label": "Supersonic Wing AC", "unit": "x/MAC", "type": "number",
         "default": "0.45"},
    ] + jet_inputs.GEOMETRY_INPUTS,
}


def run(inputs):
    try:
        config = jet_inputs.configuration(inputs)
        config.ac_supersonic = units.optional(inputs, "ac_supersonic", "", 0.45)
        cg = units.optional(inputs, "cg", "", 0.15)
        machs = [0.3, 0.6, 0.8, 0.9, 1.0, 1.1, 1.2, 1.4, 1.6, 1.8, 2.0]
        rows, margins, cnbs = [], [], []
        for m in machs:
            lon = supersonic.longitudinal_stability(config, m, cg)
            lat = supersonic.directional_stability(config, m)
            margins.append(lon["static_margin"])
            cnbs.append(lat["cn_beta"] * math.pi / 180)
            rows.append([f"{m:.1f}", f"{lon['neutral_point']:.3f}", f"{lon['static_margin']:.3f}",
                         f"{lat['cn_beta'] * math.pi / 180:.5f}"])
        r = report.Report("Supersonic Static Stability")
        g = config.wing_geometry
        r.value("Wing MAC", g["mac"], "m", 3)
        r.value("CG", cg, "x/MAC", 3)
        r.value("Body Munk shift (M0.3)",
                supersonic.longitudinal_stability(config, 0.3, cg)["body_shift"], "x/MAC", 3)
        r.table(["Mach", "Neutral pt", "Static margin", "Cn_beta /deg"], rows)
        low, high = margins[0], max(margins)
        r.section("Assessment")
        if low < 0.03:
            r.warn(f"Subsonic static margin {low:.3f} is small or negative: move the CG forward "
                   "or enlarge the horizontal tail.")
        r.bullet(f"Static margin grows from {low:.2f} to {high:.2f} MAC through Mach 1; "
                 "a large supersonic margin costs trim drag and elevator authority. Fuel "
                 "transfer aft in supersonic flight is the classic remedy.")
        if min(cnbs) <= 0:
            m_bad = machs[cnbs.index(min(cnbs))]
            r.warn(f"Directional stability is lost near Mach {m_bad:.1f}: enlarge the vertical "
                   "tail, lengthen its arm, or add a ventral fin.")
        else:
            r.bullet(f"C_n_beta stays positive (minimum {min(cnbs):.5f} /deg).")
        r.note("Neutral point by wing-tail summation with Munk body moment; downwash from the "
               "local wing lift slope. Conceptual accuracy only.")

        figures = []
        if plotting.available():
            figures.append(plotting.line_chart("Static Margin and Directional Stability vs Mach",
                                               "Mach", "Value",
                                               [("Static margin (x/MAC)", machs, margins),
                                                ("Cn_beta x 100 (/deg)", machs, [c * 100 for c in cnbs])]))
        return report.result(r, outputs={
            "Subsonic Static Margin": {"value": margins[0], "unit": ""},
            "Supersonic Static Margin": {"value": margins[machs.index(1.6)], "unit": ""},
            "Minimum Cn_beta": {"value": min(cnbs), "unit": "1/deg"}}, figures=figures)
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
