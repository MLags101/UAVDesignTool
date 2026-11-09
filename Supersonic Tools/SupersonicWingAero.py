"""
Supersonic Wing Aerodynamics

How a wing's lift slope, drag due to lift and aerodynamic centre change from
subsonic flight through Mach 2, and whether its leading edge is subsonic
(swept inside the Mach cone, so it keeps some leading-edge suction) or
supersonic.
"""

from uavlib import plotting, report, supersonic, units

TOOL_METADATA = {
    "name": "Supersonic Wing Aerodynamics",
    "category": "Supersonic / Aerodynamics",
    "description": (
        "Lift-curve slope, drag-due-to-lift factor K and aerodynamic centre versus "
        "Mach to 2.0, with the leading-edge regime at each Mach number."
    ),
    "inputs": [
        {"key": "aspect_ratio", "label": "Aspect Ratio", "type": "number", "default": "2.5"},
        {"key": "le_sweep", "label": "Leading-Edge Sweep", "unit": "deg", "type": "number",
         "default": "45"},
        {"key": "taper", "label": "Taper Ratio", "type": "number", "default": "0.25"},
        {"key": "suction", "label": "Supersonic Leading-Edge Suction", "type": "number",
         "default": "0.25", "help": "Fraction of suction kept with a subsonic leading edge: "
                                    "sharp edges 0.1-0.3, rounded 0.5+."},
        {"key": "ac_supersonic", "label": "Supersonic Aerodynamic Centre", "unit": "x/MAC",
         "type": "number", "default": "0.45"},
        {"key": "design_mach", "label": "Design Mach", "type": "number", "default": "1.6"},
    ],
}


def run(inputs):
    try:
        aspect = units.positive(inputs, "aspect_ratio", "", "Aspect ratio", 2.5)
        sweep = units.optional(inputs, "le_sweep", "deg", 45.0)
        taper = units.optional(inputs, "taper", "", 0.25)
        suction = units.optional(inputs, "suction", "", 0.25)
        ac_sup = units.optional(inputs, "ac_supersonic", "", 0.45)
        design = units.positive(inputs, "design_mach", "", "Design Mach", 1.6)
        supersonic.check_mach(design)

        machs = [round(0.1 * i, 2) for i in range(1, 21)]
        rows, slopes, ks, acs = [], [], [], []
        for m in machs:
            a = supersonic.wing_lift_slope(m, aspect, sweep, taper)
            k = supersonic.induced_drag_factor(m, aspect, sweep, taper, suction)
            ac = supersonic.aerodynamic_center(m, ac_sup)
            slopes.append(a)
            ks.append(k)
            acs.append(ac)
            edge = ""
            if m > 1:
                edge = "subsonic LE" if supersonic.leading_edge_parameter(m, sweep) < 1 else "supersonic LE"
            rows.append([f"{m:.1f}", f"{a:.3f}", f"{k:.3f}", f"{ac:.3f}", edge])

        a_d = supersonic.wing_lift_slope(design, aspect, sweep, taper)
        k_d = supersonic.induced_drag_factor(design, aspect, sweep, taper, suction)
        r = report.Report("Supersonic Wing Aerodynamics")
        r.value("Aspect ratio", aspect, "", 2)
        r.value("Leading-edge sweep", sweep, "deg", 1)
        r.value("Taper", taper, "", 2)
        r.section(f"At Design Mach {design:g}")
        r.value("Lift slope", a_d, "/rad", 3)
        r.value("K (CD = CD0 + K CL^2)", k_d, "", 4)
        m_le = supersonic.leading_edge_parameter(design, sweep) if design > 1 else None
        if m_le is not None:
            r.value("beta cot(LE sweep)", m_le if m_le != float("inf") else 99, "", 3)
            r.value("Leading edge", "subsonic" if m_le < 1 else "supersonic")
            if m_le >= 1:
                r.bullet("The leading edge is ahead of the Mach cone: no leading-edge suction, "
                         "so drag due to lift is the full CL/CL_alpha. More sweep would help.")
            else:
                r.bullet("The leading edge sits inside the Mach cone and can keep some suction "
                         "if it is rounded.")
        r.section("Versus Mach")
        r.table(["Mach", "CL_a /rad", "K", "x_ac/MAC", "Regime"], rows)
        r.bullet("The aerodynamic centre moves aft through Mach 1: the static margin grows "
                 "and so does trim drag.")
        warning = supersonic.transonic_warning(design)
        if warning:
            r.warn(warning)

        figures = []
        if plotting.available():
            figures.append(plotting.line_chart("Lift Slope and K vs Mach", "Mach",
                                               "Value", [("CL_alpha (/rad)", machs, slopes),
                                                         ("K x 10", machs, [k * 10 for k in ks]),
                                                         ("x_ac/MAC x 10", machs, [a * 10 for a in acs])]))
        return report.result(r, outputs={
            "Wing Lift Slope": {"value": a_d, "unit": "1/rad"},
            "Induced Drag Factor K": {"value": k_d, "unit": ""}}, figures=figures)
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
