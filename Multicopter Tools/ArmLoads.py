"""
Multirotor Arm Structural Loads

An arm is a cantilever with the motor thrust at its tip. Three things matter:
it must not break at the limit load, it must not deflect so much that the
attitude controller fights its own flexing, and its first bending mode must sit
clear of the motor and blade-passing frequencies -- otherwise the airframe
resonates and every camera frame is smeared.
"""

import math

from uavlib import geometry, plotting, report, structures, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Arm Structural Loads",
    "category": "Multirotor / Structures",
    "description": (
        "Bending stress, deflection and first natural frequency of a "
        "multirotor arm under motor thrust. Checks the resonance margin "
        "against motor and blade-passing frequencies."
    ),
    "inputs": [
        {"key": "arm_length", "label": "Arm Length", "unit": "m", "type": "number",
         "help": "Hub attachment to motor centre."},
        {"key": "max_thrust", "label": "Max Thrust per Motor", "unit": "N",
         "type": "number", "help": "Accepts 'gf', e.g. '900 gf'."},
        {"key": "landing_factor", "label": "Landing Load Factor", "type": "number",
         "default": "3.0",
         "help": "A hard landing loads an arm far beyond its thrust. 3-5 g is "
                 "a sensible design case."},
        {"key": "motor_mass", "label": "Motor + Prop Mass", "unit": "kg",
         "type": "number", "default": "60 g"},
        {"key": "section", "label": "Arm Section", "type": "choice",
         "choices": ["Round tube", "Solid rod", "Rectangular"],
         "default": "Round tube"},
        {"key": "material", "label": "Material", "type": "choice",
         "choices": list(structures.MATERIALS),
         "default": "Carbon fibre tube (pultruded)"},
        {"key": "dim_a", "label": "Outer Diameter / Width", "unit": "m",
         "type": "number", "default": "16 mm"},
        {"key": "dim_b", "label": "Wall Thickness / Height", "unit": "m",
         "type": "number", "default": "1 mm"},
        {"key": "safety_factor", "label": "Safety Factor", "type": "number",
         "default": "1.5"},
        {"key": "max_rpm", "label": "Maximum Motor RPM", "unit": "rpm",
         "type": "number", "help": "For the resonance check."},
        {"key": "blades", "label": "Blades per Propeller", "type": "number",
         "default": "2"},
    ],
}


def run(inputs):
    try:
        length = units.positive(inputs, "arm_length", "m", "Arm length")
        thrust = units.positive(inputs, "max_thrust", "N", "Max thrust")
        landing_factor = units.optional(inputs, "landing_factor", "", 3.0) or 3.0
        motor_mass = units.optional(inputs, "motor_mass", "kg", 0.06)
        section_type = inputs.get("section") or "Round tube"
        material_name = inputs.get("material") or "Carbon fibre tube (pultruded)"
        dim_a = units.positive(inputs, "dim_a", "m", "Outer dimension")
        dim_b = units.optional(inputs, "dim_b", "m", 0.0)
        safety = units.optional(inputs, "safety_factor", "", 1.5) or 1.5
        max_rpm = units.optional(inputs, "max_rpm", "rpm", 0.0)
        blades = int(units.optional(inputs, "blades", "", 2) or 2)

        material = structures.MATERIALS[material_name]

        if section_type == "Round tube":
            if dim_b <= 0:
                return report.error("A tube needs a wall thickness.")
            if dim_b * 2 >= dim_a:
                return report.error("Wall thickness is too large for that "
                                    "outer diameter.")
            section = structures.tube_properties(dim_a, dim_b)
            description = f"{dim_a * 1000:.1f} mm tube, {dim_b * 1000:.2f} mm wall"
        elif section_type == "Solid rod":
            section = structures.solid_rod_properties(dim_a)
            description = f"{dim_a * 1000:.1f} mm solid rod"
        else:
            if dim_b <= 0:
                return report.error("A rectangular arm needs a height.")
            section = structures.rectangular_properties(dim_a, dim_b)
            description = f"{dim_a * 1000:.1f} x {dim_b * 1000:.1f} mm"

        # The design load is the worse of full thrust and a hard landing.
        landing_load = motor_mass * G * landing_factor
        design_load = max(thrust, landing_load)
        driving = "motor thrust" if thrust >= landing_load else "landing impact"

        moment = design_load * length
        stress = structures.bending_stress(moment, section["section_modulus"])
        margin = structures.margin_of_safety(stress * safety, material["sigma"])
        deflection = structures.cantilever_deflection(
            design_load, length, material["E"], section["I"])

        mass_per_length = section["area"] * material["rho"]
        arm_mass = mass_per_length * length
        frequency = structures.natural_frequency_cantilever(
            material["E"], section["I"], length, mass_per_length, motor_mass)

        r = report.Report("Arm Structural Loads")
        r.section("Geometry")
        r.dual("Arm length", length, "m", "in", 4)
        r.value("Section", f"{section_type}: {description}")
        r.value("Material", material_name)
        r.value("Second moment of area", section["I"], "m^4", 12)
        r.value("Section modulus", section["section_modulus"], "m^3", 10)
        r.value("Arm mass", arm_mass * 1000, "g", 1)

        r.section("Loads")
        r.value("Max motor thrust", thrust, "N", 3)
        r.value("  in grams", thrust / G * 1000, "g", 0)
        r.value("Motor + prop mass", motor_mass * 1000, "g", 1)
        r.value("Landing load", landing_load, "N", 3,
                note=f"{landing_factor:g} g")
        r.value("Design load", design_load, "N", 3, note=f"set by {driving}")
        r.value("Root bending moment", moment, "N.m", 4)

        r.section("Stress and Stiffness")
        r.value("Bending stress", stress / 1e6, "MPa", 1)
        r.value("With safety factor", stress * safety / 1e6, "MPa", 1)
        r.value("Allowable stress", material["sigma"] / 1e6, "MPa", 0)
        r.value("Margin of safety", margin, "", 3)
        r.dual("Tip deflection", deflection, "m", "in", 5)
        r.value("  as % of arm length", 100 * deflection / length, "%", 2)
        r.value("Tilt at motor", math.degrees(math.atan(1.5 * deflection / length)),
                "deg", 3)

        if margin < 0:
            r.warn(f"FAILS at the design load by {-margin * 100:.0f}%. "
                   "Increase diameter or wall thickness.")
        elif margin < 0.3:
            r.warn("Marginal. Arms take repeated impact loads in normal use; "
                   "aim for a margin above 0.5.")
        else:
            r.bullet(f"Strength margin of {margin:.2f} is adequate.")

        if deflection / length > 0.02:
            r.warn("Deflection above 2% of arm length tilts the thrust vector "
                   "enough to degrade attitude control.")

        r.section("Resonance")
        r.value("First bending mode", frequency, "Hz", 1)
        if max_rpm > 0:
            motor_hz = max_rpm / 60.0
            blade_hz = motor_hz * blades
            r.value("Motor rotation frequency", motor_hz, "Hz", 1,
                    note=f"{max_rpm:.0f} rpm")
            r.value("Blade passing frequency", blade_hz, "Hz", 1,
                    note=f"{blades} blades")
            r.value("Margin over blade passing", frequency / blade_hz, "x", 2)

            if frequency < blade_hz * 1.5:
                r.warn(f"The arm's first mode ({frequency:.0f} Hz) is close to "
                       f"the blade passing frequency ({blade_hz:.0f} Hz). "
                       "Expect resonance, blurred video and accelerated "
                       "fatigue. Stiffen or shorten the arm.")
            elif frequency < blade_hz * 2.5:
                r.bullet("Acceptable separation, though soft mounts for the "
                         "flight controller are still worthwhile.")
            else:
                r.bullet("Well clear of the excitation frequencies.")
        else:
            r.text("  Enter the maximum motor RPM to check the resonance "
                   "margin, which is usually the binding constraint on a "
                   "camera platform.")

        r.section("Sizing Comparison")
        rows = []
        for scale in (0.75, 0.875, 1.0, 1.125, 1.25):
            if section_type == "Round tube":
                scaled = structures.tube_properties(dim_a * scale, dim_b)
                label = f"{dim_a * scale * 1000:.1f} mm OD"
            elif section_type == "Solid rod":
                scaled = structures.solid_rod_properties(dim_a * scale)
                label = f"{dim_a * scale * 1000:.1f} mm dia"
            else:
                scaled = structures.rectangular_properties(dim_a, dim_b * scale)
                label = f"{dim_b * scale * 1000:.1f} mm high"
            s = structures.bending_stress(moment, scaled["section_modulus"])
            d = structures.cantilever_deflection(design_load, length,
                                                 material["E"], scaled["I"])
            mpl = scaled["area"] * material["rho"]
            f = structures.natural_frequency_cantilever(
                material["E"], scaled["I"], length, mpl, motor_mass)
            rows.append([label, f"{s / 1e6:.1f}",
                         f"{structures.margin_of_safety(s * safety, material['sigma']):.2f}",
                         f"{d * 1000:.2f}", f"{f:.0f}",
                         f"{mpl * length * 1000:.0f}",
                         "<-- chosen" if abs(scale - 1.0) < 1e-9 else ""])
        r.table(["Section", "MPa", "Margin", "Defl mm", "Hz", "Mass g", ""], rows)
        r.text("  Diameter buys stiffness far more cheaply than wall thickness:")
        r.text("  stiffness goes as the fourth power of diameter, mass only as")
        r.text("  the first.")

        figures = []
        if plotting.available():
            try:
                diameters, frequencies, masses = [], [], []
                for i in range(8, 36):
                    d_outer = i / 1000.0
                    if section_type == "Round tube" and dim_b * 2 >= d_outer:
                        continue
                    if section_type == "Round tube":
                        scaled = structures.tube_properties(d_outer, dim_b)
                    elif section_type == "Solid rod":
                        scaled = structures.solid_rod_properties(d_outer)
                    else:
                        scaled = structures.rectangular_properties(dim_a, d_outer)
                    mpl = scaled["area"] * material["rho"]
                    diameters.append(d_outer * 1000)
                    frequencies.append(structures.natural_frequency_cantilever(
                        material["E"], scaled["I"], length, mpl, motor_mass))
                    masses.append(mpl * length * 1000)
                markers = [(f"Chosen {dim_a * 1000:.0f} mm", dim_a * 1000, frequency)]
                if max_rpm > 0:
                    markers.append((f"Blade passing {max_rpm / 60 * blades:.0f} Hz",
                                    diameters[0], max_rpm / 60 * blades))
                figures.append(plotting.line_chart(
                    "First Bending Mode vs Arm Size", "Outer dimension (mm)",
                    "Frequency (Hz)", [("Natural frequency", diameters, frequencies)],
                    markers=markers))
            except Exception:
                r.note("Chart could not be generated.")

        return report.result(r, outputs={
            "Arm Bending Stress": {"value": stress / 1e6, "unit": "MPa"},
            "Arm Margin of Safety": {"value": margin},
            "Arm Tip Deflection": {"value": deflection, "unit": "m"},
            "Arm Natural Frequency": {"value": frequency, "unit": "Hz"},
            "Arm Mass": {"value": arm_mass, "unit": "kg"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
