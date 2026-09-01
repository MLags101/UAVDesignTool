"""
Wing Spar Sizing

Sizes the main spar for the bending it has to carry at the design load factor.
The lift distribution matters: an elliptical distribution puts its centroid at
4/(3*pi) of the semi-span, noticeably inboard of the mid-span point a uniform
distribution assumes, so assuming uniform is the conservative choice.

Reports stress, margin of safety and tip deflection for tubes, solid rods and
built-up cap-and-web spars.
"""

import math

from uavlib import plotting, report, structures, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Wing Spar Sizing",
    "category": "Fixed Wing / Structures",
    "description": (
        "Root bending moment, stress, margin of safety and tip deflection for "
        "a wing spar at a chosen load factor. Supports carbon tube, solid rod, "
        "rectangular and built-up cap-and-web sections."
    ),
    "inputs": [
        {"key": "mass", "label": "All-Up Mass", "unit": "kg", "type": "number"},
        {"key": "span", "label": "Wing Span", "unit": "m", "type": "number"},
        {"key": "load_factor", "label": "Design Load Factor", "unit": "g",
         "type": "number", "default": "4.0",
         "help": "Manoeuvre limit. 3-4 for a trainer, 6-9 for aerobatic."},
        {"key": "safety_factor", "label": "Safety Factor", "type": "number",
         "default": "1.5"},
        {"key": "distribution", "label": "Lift Distribution", "type": "choice",
         "choices": ["Elliptical", "Uniform (conservative)"],
         "default": "Elliptical"},
        {"key": "section", "label": "Spar Section", "type": "choice",
         "choices": ["Round tube", "Solid rod", "Rectangular",
                     "Cap and web (built-up)"],
         "default": "Round tube"},
        {"key": "material", "label": "Material", "type": "choice",
         "choices": list(structures.MATERIALS),
         "default": "Carbon fibre tube (pultruded)"},
        {"key": "dim_a", "label": "Outer Diameter / Width / Cap Width",
         "unit": "m", "type": "number",
         "help": "Tube or rod: outer diameter. Rectangular: width. "
                 "Cap and web: cap width. Accepts mm."},
        {"key": "dim_b", "label": "Wall / Height / Cap Thickness", "unit": "m",
         "type": "number",
         "help": "Tube: wall thickness. Rectangular: height. Cap and web: cap "
                 "thickness. Not used for a solid rod."},
        {"key": "dim_c", "label": "Cap Separation", "unit": "m", "type": "number",
         "help": "Cap and web only: distance between the caps, roughly the "
                 "aerofoil thickness at the spar."},
    ],
}


def run(inputs):
    try:
        mass = units.positive(inputs, "mass", "kg", "All-up mass")
        span = units.positive(inputs, "span", "m", "Span")
        load_factor = units.positive(inputs, "load_factor", "", "Load factor",
                                     default=4.0)
        safety = units.optional(inputs, "safety_factor", "", 1.5) or 1.5
        distribution = inputs.get("distribution") or "Elliptical"
        section_type = inputs.get("section") or "Round tube"
        material_name = inputs.get("material") or "Carbon fibre tube (pultruded)"
        dim_a = units.positive(inputs, "dim_a", "m", "First spar dimension")
        dim_b = units.optional(inputs, "dim_b", "m", 0.0)
        dim_c = units.optional(inputs, "dim_c", "m", 0.0)

        material = structures.MATERIALS[material_name]

        if section_type == "Round tube":
            if dim_b <= 0:
                return report.error("A tube needs a wall thickness.")
            if dim_b * 2 >= dim_a:
                return report.error("Wall thickness is too large for that outer "
                                    "diameter; the tube would have no bore.")
            section = structures.tube_properties(dim_a, dim_b)
            height = dim_a
            description = (f"{dim_a * 1000:.1f} mm tube, "
                           f"{dim_b * 1000:.2f} mm wall")
        elif section_type == "Solid rod":
            section = structures.solid_rod_properties(dim_a)
            height = dim_a
            description = f"{dim_a * 1000:.1f} mm solid rod"
        elif section_type == "Rectangular":
            if dim_b <= 0:
                return report.error("A rectangular spar needs a height.")
            section = structures.rectangular_properties(dim_a, dim_b)
            height = dim_b
            description = f"{dim_a * 1000:.1f} x {dim_b * 1000:.1f} mm"
        else:
            if dim_b <= 0 or dim_c <= 0:
                return report.error("A cap-and-web spar needs a cap thickness "
                                    "and a cap separation.")
            section = structures.spar_cap_properties(dim_a, dim_b, dim_c)
            height = dim_c + dim_b
            description = (f"caps {dim_a * 1000:.1f} x {dim_b * 1000:.2f} mm, "
                           f"{dim_c * 1000:.1f} mm apart")

        lift = mass * G * load_factor
        if distribution == "Elliptical":
            root_moment = structures.elliptical_lift_root_moment(lift, span)
            centroid = 4.0 / (3.0 * math.pi)
        else:
            root_moment = structures.uniform_lift_root_moment(lift, span)
            centroid = 0.5

        stress = structures.bending_stress(root_moment, section["section_modulus"])
        margin = structures.margin_of_safety(stress * safety, material["sigma"])
        shear = structures.wing_shear_at_root(lift)

        # Deflection from an equivalent tip load producing the same root moment.
        half_span = span / 2.0
        equivalent_tip_load = root_moment / half_span
        deflection = structures.cantilever_deflection(
            equivalent_tip_load, half_span, material["E"], section["I"])

        spar_mass = section["area"] * span * material["rho"]

        r = report.Report("Wing Spar Sizing")
        r.section("Loading")
        r.dual("All-up mass", mass, "kg", "lb", 3)
        r.value("Design load factor", load_factor, "g", 2)
        r.value("Safety factor", safety, "", 2)
        r.value("Total lift at limit", lift, "N", 2)
        r.value("Lift distribution", distribution)
        r.value("Load centroid", centroid, "of semi-span", 4)
        r.dual("Semi-span", half_span, "m", "in", 4)

        r.section("Root Loads")
        r.value("Root bending moment", root_moment, "N.m", 3)
        r.value("Root shear", shear, "N", 2)
        if distribution == "Elliptical":
            uniform = structures.uniform_lift_root_moment(lift, span)
            r.value("Uniform-distribution moment", uniform, "N.m", 3,
                    note=f"{100 * (uniform / root_moment - 1):.0f}% higher")

        r.section("Section")
        r.value("Type", section_type)
        r.value("Dimensions", description)
        r.value("Material", material_name)
        r.value("Young's modulus", material["E"] / 1e9, "GPa", 1)
        r.value("Allowable stress", material["sigma"] / 1e6, "MPa", 0)
        r.value("Second moment of area", section["I"], "m^4", 12)
        r.value("Section modulus", section["section_modulus"], "m^3", 10)
        r.value("Cross-sectional area", section["area"] * 1e6, "mm^2", 2)
        r.value("Spar mass (full span)", spar_mass * 1000, "g", 1)
        r.value("  as % of all-up mass", 100 * spar_mass / mass, "%", 1)

        r.section("Stress and Deflection")
        r.value("Bending stress", stress / 1e6, "MPa", 1)
        r.value("With safety factor", stress * safety / 1e6, "MPa", 1)
        r.value("Allowable", material["sigma"] / 1e6, "MPa", 0)
        r.value("Margin of safety", margin, "", 3)
        r.value("Stress utilisation", 100 * stress * safety / material["sigma"],
                "%", 1)
        r.dual("Tip deflection", deflection, "m", "in", 4)
        r.value("  as % of semi-span", 100 * deflection / half_span, "%", 2)
        r.blank()
        r.text(f"  {structures.deflection_note(deflection, half_span)}")

        r.section("Verdict")
        if margin < 0:
            r.warn(f"FAILS. Stress exceeds the allowable by "
                   f"{-margin * 100:.0f}% at the design load. This spar will "
                   "break before reaching the limit load factor.")
            required_z = structures.required_section_modulus(
                root_moment, material["sigma"], safety)
            r.value("Required section modulus", required_z, "m^3", 10)
            r.value("Ratio needed", required_z / section["section_modulus"],
                    "x current", 2)
        elif margin < 0.2:
            r.warn(f"Marginal: only {margin * 100:.0f}% above the allowable "
                   "stress. Little tolerance for a hard landing or a "
                   "material flaw.")
        elif margin > 3:
            r.bullet(f"Very conservative ({margin:.1f} margin). A lighter "
                     "section would still carry the load.")
        else:
            r.bullet(f"Adequate: {margin * 100:.0f}% margin above the "
                     "allowable stress at the design load.")

        if deflection / half_span > 0.05:
            r.warn("Tip deflection above 5% of semi-span will change the "
                   "effective dihedral in flight and can lead to flutter.")

        r.section("Sensitivity")
        r.text("  Bending stiffness rises with the cube of depth, so making a")
        r.text("  spar deeper always beats making it thicker:")
        r.blank()
        rows = []
        for scale in (0.8, 0.9, 1.0, 1.1, 1.25):
            if section_type == "Round tube":
                scaled = structures.tube_properties(dim_a * scale, dim_b)
                label = f"{dim_a * scale * 1000:.1f} mm OD"
            elif section_type == "Solid rod":
                scaled = structures.solid_rod_properties(dim_a * scale)
                label = f"{dim_a * scale * 1000:.1f} mm dia"
            elif section_type == "Rectangular":
                scaled = structures.rectangular_properties(dim_a, dim_b * scale)
                label = f"{dim_b * scale * 1000:.1f} mm high"
            else:
                scaled = structures.spar_cap_properties(dim_a, dim_b,
                                                        dim_c * scale)
                label = f"{dim_c * scale * 1000:.1f} mm apart"
            scaled_stress = structures.bending_stress(root_moment,
                                                      scaled["section_modulus"])
            scaled_margin = structures.margin_of_safety(scaled_stress * safety,
                                                        material["sigma"])
            rows.append([label, f"{scaled_stress / 1e6:.1f}",
                         f"{scaled_margin:.2f}",
                         f"{scaled['area'] * span * material['rho'] * 1000:.0f}",
                         "<-- chosen" if abs(scale - 1.0) < 1e-9 else ""])
        r.table(["Section", "MPa", "Margin", "Mass g", ""], rows)

        figures = []
        if plotting.available():
            try:
                stations, moments = [], []
                for i in range(41):
                    y = half_span * i / 40.0
                    eta = y / half_span if half_span else 0
                    if distribution == "Elliptical":
                        # Moment falls off faster than linearly outboard.
                        remaining = (1 - eta ** 2) ** 1.5
                    else:
                        remaining = (1 - eta) ** 2
                    stations.append(y)
                    moments.append(root_moment * remaining)
                figures.append(plotting.line_chart(
                    "Bending Moment Along Span", "Distance from root (m)",
                    "Bending moment (N.m)", [("Moment", stations, moments)],
                    markers=[(f"Root {root_moment:.1f} N.m", 0.0, root_moment)]))
            except Exception:
                r.note("Chart could not be generated.")

        return report.result(r, outputs={
            "Root Bending Moment": {"value": root_moment, "unit": "N.m"},
            "Spar Stress": {"value": stress / 1e6, "unit": "MPa"},
            "Margin of Safety": {"value": margin},
            "Tip Deflection": {"value": deflection, "unit": "m"},
            "Spar Mass": {"value": spar_mass, "unit": "kg"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
