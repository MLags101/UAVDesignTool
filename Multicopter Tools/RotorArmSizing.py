"""
Frame Layout and Arm Sizing

Extends the earlier arm-length calculation, which assumed one motor per arm and
so could not express the coaxial layouts. Over-under frames (X8, Y6) carry two
motors per arm, which is the whole reason they exist: octocopter thrust and
redundancy on a quad-sized frame.

Arm length for a radial frame follows from the polygon geometry:

    R = S / (2 * sin(pi / n))       with S = spacing factor * rotor diameter

where n is the number of ARMS, not the number of motors.
"""

import math

from uavlib import geometry, plotting, propulsion, report, units

TOOL_METADATA = {
    "name": "Frame Layout & Arm Sizing",
    "category": "Multirotor / Geometry",
    "description": (
        "Arm length, tip clearance, frame class and motor positions for every "
        "common layout: tricopter, quad (X, + and H), hex, Y6, octo and X8 "
        "over-under. Reports the coaxial efficiency penalty where it applies."
    ),
    "inputs": [
        {"key": "layout", "label": "Frame Layout", "type": "choice",
         "choices": list(geometry.LAYOUTS), "default": "Quadcopter X"},
        {"key": "rotor_diameter", "label": "Rotor Diameter", "unit": "m",
         "type": "number", "help": "Accepts inches, e.g. '10 in' or '10x4.7'."},
        {"key": "spacing_factor", "label": "Spacing Factor", "type": "number",
         "default": "1.2", "min": 1.0, "max": 2.5,
         "help": "Rotor centre spacing divided by diameter. 1.05 very compact, "
                 "1.2 balanced, 1.5+ best efficiency."},
        {"key": "arm_length", "label": "Arm Length Override", "unit": "m",
         "type": "number",
         "help": "Optional. Give an existing arm length to check its clearance "
                 "instead of sizing a new one."},
        {"key": "mass", "label": "All-Up Mass", "unit": "kg", "type": "number",
         "help": "Optional. Adds thrust and disk loading figures."},
        {"key": "thrust_per_motor", "label": "Motor Max Thrust", "unit": "N",
         "type": "number", "help": "Optional. Accepts 'gf', e.g. '900 gf'."},
    ],
}


def run(inputs):
    try:
        layout_name = inputs.get("layout") or "Quadcopter X"
        frame_spec = geometry.layout(layout_name)
        diameter = units.positive(inputs, "rotor_diameter", "m", "Rotor diameter")
        spacing = units.optional(inputs, "spacing_factor", "", 1.2) or 1.2
        override = units.optional(inputs, "arm_length", "m", 0.0)
        mass = units.optional(inputs, "mass", "kg", 0.0)
        thrust_each = units.optional(inputs, "thrust_per_motor", "N", 0.0)

        if spacing < 1.0:
            return report.error("A spacing factor below 1.0 means the rotors "
                                "overlap. Use at least 1.0.")

        is_h_frame = layout_name == "H-frame Quad"
        if override > 0:
            arm = override
        elif is_h_frame:
            # The H layout is rectangular; size it so the diagonal neighbours
            # clear, then report the box dimensions.
            arm = geometry.arm_length_for_clearance(diameter, 4, spacing)
        else:
            arm = geometry.arm_length_for_clearance(diameter, frame_spec.arms,
                                                    spacing)

        frame = geometry.layout(layout_name, arm)
        clearance = geometry.tip_clearance(arm, frame.arms, diameter)
        centre_spacing = 2.0 * arm * math.sin(math.pi / frame.arms)

        r = report.Report("Frame Layout")
        r.section("Configuration")
        r.value("Layout", layout_name)
        r.value("Motors", frame.motors, "", 0)
        r.value("Structural arms", frame.arms, "", 0)
        r.value("Motors per arm", frame.motors // frame.arms, "", 0)
        r.value("Coaxial (over-under)", "Yes" if frame.coaxial else "No")
        if frame.yaw_by_servo:
            r.value("Yaw control", "Servo-tilted rear motor")
        r.blank()
        r.text(f"  {frame.notes}")

        r.section("Geometry")
        r.dual("Rotor diameter", diameter, "m", "in", 4)
        r.value("Spacing factor", spacing, "", 2)
        r.dual("Arm length (hub to motor)", arm, "m", "in", 4)
        r.dual("Motor centre spacing", centre_spacing, "m", "in", 4)
        r.dual("Motor-to-motor diagonal", arm * 2.0, "m", "in", 4)
        r.dual("Rotor tip clearance", clearance, "m", "in", 4)
        r.value("Frame class", geometry.frame_size_class(arm))
        r.dual("Swept disk envelope", arm * 2.0 + diameter, "m", "in", 4)

        if clearance < 0:
            r.warn(f"Rotors OVERLAP by {abs(clearance) * 1000:.0f} mm. Either "
                   "shorten the props or lengthen the arms.")
        elif clearance < 0.02:
            r.warn(f"Only {clearance * 1000:.0f} mm of tip clearance. Blade "
                   "flex under load can cause a strike.")

        r.section("Efficiency")
        if spacing < 1.1:
            r.bullet("Compact spacing. Rotors interfere strongly: expect more "
                     "noise, more vibration and reduced thrust.")
        elif spacing <= 1.3:
            r.bullet("Balanced spacing. The standard choice for utility and "
                     "camera airframes.")
        else:
            r.bullet("Generous spacing. Best aerodynamic efficiency, at the "
                     "cost of a larger and heavier frame.")

        if frame.coaxial:
            r.blank()
            r.value("Coaxial thrust penalty",
                    geometry.COAXIAL_PENALTY * 100, "%", 0)
            r.text("  The lower rotor works in the upper rotor's downwash, so a")
            r.text("  coaxial pair produces roughly 80% of two isolated rotors.")
            flat_arms = frame.motors
            flat_arm_length = geometry.arm_length_for_clearance(
                diameter, flat_arms, spacing)
            r.value(f"Equivalent flat {flat_arms}-rotor arm", flat_arm_length,
                    "m", 4)
            r.value("Frame size saving", 100.0 * (1 - arm / flat_arm_length),
                    "%", 1)
            r.text("  That size saving is what you buy with the 20% penalty.")

        if is_h_frame:
            r.blank()
            r.text("  H-frame motor positions are rectangular rather than")
            r.text("  radial: longer fore-and-aft, which suits a forward camera")
            r.text("  and a long battery bay.")

        r.section("Motor Positions")
        rows = []
        for row in geometry.mixing_matrix(frame):
            rows.append([f"M{row['motor']}", f"arm {row['arm']}", row["level"],
                         f"{row['x']:+.3f}", f"{row['y']:+.3f}", row["spin"]])
        r.table(["Motor", "Arm", "Level", "X (m)", "Y (m)", "Rotation"], rows)
        r.text("  +X is the nose. Rotation alternates so reaction torques cancel.")

        outputs = {
            "Arm Length": {"value": arm, "unit": "m"},
            "Motor Count": {"value": frame.motors},
            "Frame Diagonal": {"value": arm * 2.0, "unit": "m"},
        }

        if mass > 0:
            from uavlib.atmosphere import G
            weight = mass * G
            effective = frame.motors * (1 - geometry.COAXIAL_PENALTY) \
                if frame.coaxial else frame.motors
            r.section("Loading")
            r.dual("All-up mass", mass, "kg", "lb", 3)
            r.value("Hover thrust per rotor", weight / effective, "N", 3)
            r.value("  in grams", weight / effective / G * 1000, "g", 0)
            r.value("Disk loading", propulsion.disk_loading(
                weight, diameter, frame.motors), "N/m^2", 2)
            outputs["Hover Thrust per Motor"] = {"value": weight / effective,
                                                 "unit": "N"}

            if thrust_each > 0:
                total = geometry.effective_thrust(thrust_each, frame)
                ratio = total / weight
                r.value("Max thrust per motor", thrust_each, "N", 3)
                r.value("Total available thrust", total, "N", 2)
                r.value("Thrust-to-weight ratio", ratio, ":1", 2)
                r.value("Hover throttle", 100.0 / ratio, "%", 1)
                if ratio < 1.5:
                    r.warn("Thrust-to-weight below 1.5 leaves no authority for "
                           "manoeuvre or wind. 2:1 is the practical minimum.")
                elif ratio < 2.0:
                    r.bullet("Adequate for gentle camera work only.")
                elif ratio < 3.0:
                    r.bullet("Good general-purpose margin.")
                else:
                    r.bullet("Sporty to aerobatic margin.")
                outputs["Thrust-to-Weight Ratio"] = {"value": ratio}

        figures = []
        if plotting.available():
            try:
                # One disk per arm, since coaxial pairs share a position.
                circles = [((x, y), diameter / 2.0) for x, y in frame.positions]
                labels = []
                for index in range(len(frame.positions)):
                    per_arm = frame.motors // frame.arms
                    if per_arm > 1:
                        labels.append(f"A{index + 1} x{per_arm}")
                    else:
                        labels.append(f"M{index + 1}")
                figures.append(plotting.scatter_layout(
                    f"{layout_name} Plan View", frame.positions, labels, circles))
            except Exception:
                r.note("Chart could not be generated.")

        return report.result(r, outputs=outputs, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
