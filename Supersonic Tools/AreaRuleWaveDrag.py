"""
Area Rule & Wave Drag

Builds the aircraft's cross-sectional area distribution (fuselage, exposed
wing, tails, minus the inlet stream tube), computes its slender-body wave drag
and compares it with the ideal Sears-Haack body. Stations where the aircraft
bulges above the ideal are where to waist the fuselage. A measured or CAD
distribution can be supplied as a CSV of x,area instead.
"""

import csv
import os

from uavlib import area_rule, jet_inputs, plotting, report, supersonic, units

TOOL_METADATA = {
    "name": "Area Rule & Wave Drag",
    "category": "Supersonic / Aerodynamics",
    "description": (
        "Cross-sectional area distribution, slender-body (Eminton-Lord) wave drag "
        "and comparison with the Sears-Haack minimum; shows where to area-rule."
    ),
    "inputs": jet_inputs.GEOMETRY_INPUTS + [
        {"key": "area_file", "label": "Area Distribution CSV (optional)", "type": "file",
         "help": "Two columns x (m), area (m^2), header row allowed. Overrides the geometry."},
    ],
}


def _read_csv(path):
    xs, areas = [], []
    with open(path, newline="", encoding="utf-8") as stream:
        for row in csv.reader(stream):
            if len(row) < 2:
                continue
            try:
                xs.append(float(row[0]))
                areas.append(float(row[1]))
            except ValueError:
                if xs:
                    raise ValueError(f"Unreadable row in {os.path.basename(path)}: {row}")
    return xs, areas


def run(inputs):
    try:
        path = (inputs.get("area_file") or "").strip()
        config = None
        if path:
            xs, areas = _read_csv(path)
            source = os.path.basename(path)
        else:
            config = jet_inputs.configuration(inputs)
            xs, areas = config.area_distribution()
            source = "geometry inputs"
        dq = area_rule.wave_drag_dq(xs, areas)
        sh = area_rule.equivalent_sears_haack(xs, areas)
        ratio = dq / sh["dq_same_max_area"]

        r = report.Report("Area Rule & Wave Drag")
        r.value("Source", source)
        r.value("Length", sh["length"], "m", 3)
        r.value("Maximum area", sh["max_area"], "m^2", 5)
        r.value("Volume", sh["volume"], "m^3", 4)
        r.section("Wave Drag at Mach 1 (normal cuts)")
        r.value("This distribution, D/q", dq, "m^2", 5)
        r.value("Sears-Haack, same max area", sh["dq_same_max_area"], "m^2", 5)
        r.value("Sears-Haack, same volume", sh["dq_same_volume"], "m^2", 5)
        r.value("Ratio to Sears-Haack (E_WD)", ratio, "", 2)
        outputs = {"Wave D/q (Mach 1)": {"value": dq, "unit": "m^2"},
                   "Effective E_WD": {"value": ratio, "unit": ""}}
        if config is not None:
            r.value("CD wave on wing area", dq / config.wing_area, "", 5)
            cd16 = supersonic.supersonic_wave_dq(1.6, sh["dq_same_max_area"], ratio,
                                                 config.le_sweep_deg) / config.wing_area
            r.value("CD wave at Mach 1.6 (Raymer)", cd16, "", 5)

        # Where the aircraft exceeds the ideal body of equal volume.
        x0 = xs[0]
        excess = []
        for x, a in zip(xs, areas):
            ideal = area_rule.sears_haack_area(x - x0, sh["length"], sh["max_area_same_volume"])
            excess.append(a - ideal)
        worst = sorted(range(len(xs)), key=lambda i: -excess[i])[:1]
        r.section("Interpretation")
        if ratio < 1.5:
            r.bullet("Close to Sears-Haack: the distribution is already well area-ruled.")
        elif ratio < 2.5:
            r.bullet("Typical of conventional supersonic designs.")
        else:
            r.bullet("Well above Sears-Haack: abrupt area changes are costing wave drag.")
        if worst and excess[worst[0]] > 0:
            i = worst[0]
            r.bullet(f"Largest excess over the equal-volume ideal is at x = {xs[i]:.2f} m "
                     f"(+{excess[i]:.4f} m^2): waist the fuselage there or move volume fore/aft.")
        r.bullet("Normal-cut (Mach 1) wave drag; at higher Mach, oblique cuts smooth the "
                 "distribution and Raymer's Mach correction applies.")
        r.note("A blunt base that the exhaust does not fill violates slender-body theory.")

        figures = []
        if plotting.available():
            ideal = [area_rule.sears_haack_area(x - x0, sh["length"], sh["max_area_same_volume"])
                     for x in xs]
            figures.append(plotting.line_chart("Cross-Sectional Area Distribution", "x (m)",
                                               "Area (m^2)", [("Aircraft", xs, areas),
                                                              ("Sears-Haack, equal volume", xs, ideal)]))
        return report.result(r, outputs=outputs, figures=figures)
    except (units.UnitError, ValueError, OSError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
