"""
Mach Drag Build-up

Zero-lift drag from subsonic cruise through the transonic drag rise to Mach 2:
component skin friction with compressibility, form factors, and wave drag
from the Sears-Haack body scaled by E_WD. Also reports drag-divergence Mach
and maximum L/D at each Mach.
"""

from uavlib import jet_inputs, plotting, report, supersonic, units

TOOL_METADATA = {
    "name": "Mach Drag Build-up",
    "category": "Supersonic / Aerodynamics",
    "description": (
        "CD0 versus Mach (friction, wave, miscellaneous) for a wing-body-tail jet, "
        "with drag-divergence Mach and L/D max from Mach 0.3 to 2."
    ),
    "inputs": jet_inputs.GEOMETRY_INPUTS + [
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number",
         "default": "11000"},
    ],
}


def run(inputs):
    try:
        config = jet_inputs.configuration(inputs)
        altitude = units.optional(inputs, "altitude", "m", 11000.0)
        machs = [0.3, 0.5, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2, 1.3, 1.4, 1.5,
                 1.6, 1.7, 1.8, 1.9, 2.0]
        rows, friction, wave, total, lds = [], [], [], [], []
        for m in machs:
            d = config.cd0(m, altitude)
            ld = config.lift_to_drag_max(m, altitude)[0]
            friction.append(d["friction_total"])
            wave.append(d["wave"])
            total.append(d["total"])
            lds.append(ld)
            rows.append([f"{m:.2f}", f"{d['friction_total']:.5f}", f"{d['wave']:.5f}",
                         f"{d['total']:.5f}", f"{config.k_factor(m):.3f}", f"{ld:.2f}"])
        sub = config.cd0(0.8, altitude)
        sup = config.cd0(1.6, altitude)
        sh = config.sears_haack

        r = report.Report("Mach Drag Build-up")
        r.value("Reference (wing) area", config.wing_area, "m^2", 3)
        r.value("Span", config.span, "m", 3)
        r.value("Altitude", altitude, "m", 0)
        r.section("Geometry")
        surfaces, _lengths = config.wetted_areas()
        for name, area in surfaces.items():
            r.value(f"Wetted area, {name}", area, "m^2", 3)
        r.value("Maximum cross-section", sh["max_area"], "m^2", 4)
        r.value("Sears-Haack D/q (same Amax)", sh["dq_same_max_area"], "m^2", 5)
        r.section("Transonic")
        r.value("Drag-divergence Mach", sub["m_dd"], "", 3)
        r.value("Drag-rise onset (critical)", sub["m_cr"], "", 3)
        r.section("Friction Breakdown at Mach 0.8 / 1.6")
        r.table(["Component", "CD0 M0.8", "CD0 M1.6"],
                [[k, f"{sub['friction'][k]:.5f}", f"{sup['friction'].get(k, 0):.5f}"]
                 for k in sub["friction"]])
        r.section("Versus Mach")
        r.table(["Mach", "Friction", "Wave", "CD0", "K", "L/D max"], rows)
        peak = max(range(len(machs)), key=lambda i: total[i])
        r.bullet(f"Drag peaks near Mach {machs[peak]:.2f} at {total[peak] / total[0]:.1f}x the "
                 "subsonic value: the transonic pinch the engine must push through.")
        r.bullet("Wave drag scales with E_WD and (A_max/length)^2: a longer, slimmer, "
                 "area-ruled body is the main lever.")
        r.warn("Mach 0.9-1.2 values are a faired interpolation (Raymer); treat them as estimates.")

        figures = []
        if plotting.available():
            figures.append(plotting.line_chart("Zero-Lift Drag vs Mach", "Mach", "CD0",
                                               [("Total", machs, total), ("Friction", machs, friction),
                                                ("Wave", machs, wave)]))
            figures.append(plotting.line_chart("Maximum L/D vs Mach", "Mach", "L/D max",
                                               [("L/D max", machs, lds)]))
        return report.result(r, outputs={
            "CD0 Subsonic (M0.8)": {"value": sub["total"], "unit": ""},
            "CD0 Supersonic (M1.6)": {"value": sup["total"], "unit": ""},
            "Drag Divergence Mach": {"value": sub["m_dd"], "unit": ""},
            "L/D max (M1.6)": {"value": config.lift_to_drag_max(1.6, altitude)[0], "unit": ""}},
            figures=figures)
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
