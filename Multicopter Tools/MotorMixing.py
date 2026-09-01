"""
Motor Mixing and Control Authority

Shows which motor does what for a given roll, pitch and yaw demand, and whether
any motor saturates. Saturation is the real limit on a multirotor's authority:
a motor cannot push below zero thrust, and it cannot exceed its maximum, so a
frame with little thrust margin loses control authority long before it loses
the ability to hover.

Covers the layouts that behave differently from a plain quad: the tricopter
(which yaws with a servo, not with reaction torque) and the coaxial X8 and Y6
(where two motors share one arm and counter-rotate).
"""

from uavlib import geometry, plotting, propulsion, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Motor Mixing & Control Authority",
    "category": "Multirotor / Control",
    "description": (
        "Per-motor thrust for a commanded roll, pitch and yaw, with a "
        "saturation check. Reveals how much control authority a given "
        "thrust-to-weight ratio actually buys."
    ),
    "inputs": [
        {"key": "layout", "label": "Frame Layout", "type": "choice",
         "choices": list(geometry.LAYOUTS), "default": "Quadcopter X"},
        {"key": "mass", "label": "All-Up Mass", "unit": "kg", "type": "number"},
        {"key": "max_thrust", "label": "Max Thrust per Motor", "unit": "N",
         "type": "number", "help": "Accepts 'gf', e.g. '900 gf'."},
        {"key": "arm_length", "label": "Arm Length", "unit": "m", "type": "number",
         "default": "0.25"},
        {"key": "roll", "label": "Roll Demand", "unit": "fraction of hover",
         "type": "number", "default": "0.3", "min": -1.0, "max": 1.0},
        {"key": "pitch", "label": "Pitch Demand", "unit": "fraction of hover",
         "type": "number", "default": "0.0", "min": -1.0, "max": 1.0},
        {"key": "yaw", "label": "Yaw Demand", "unit": "fraction of hover",
         "type": "number", "default": "0.0", "min": -1.0, "max": 1.0},
    ],
}


def run(inputs):
    try:
        layout_name = inputs.get("layout") or "Quadcopter X"
        mass = units.positive(inputs, "mass", "kg", "All-up mass")
        max_thrust = units.optional(inputs, "max_thrust", "N", 0.0)
        arm = units.positive(inputs, "arm_length", "m", "Arm length", default=0.25)
        roll = units.optional(inputs, "roll", "", 0.0)
        pitch = units.optional(inputs, "pitch", "", 0.0)
        yaw = units.optional(inputs, "yaw", "", 0.0)

        frame = geometry.layout(layout_name, arm)
        weight = mass * G
        effective = frame.motors * (1 - geometry.COAXIAL_PENALTY) \
            if frame.coaxial else frame.motors
        hover_each = weight / effective

        rows = geometry.motor_demands(frame, hover_each, roll, pitch, yaw)

        r = report.Report("Motor Mixing")
        r.section("Configuration")
        r.value("Layout", layout_name)
        r.value("Motors", frame.motors, "", 0)
        r.value("Arms", frame.arms, "", 0)
        r.dual("All-up mass", mass, "kg", "lb", 3)
        r.dual("Arm length", arm, "m", "in", 4)
        r.value("Hover thrust per motor", hover_each, "N", 3)
        r.value("  in grams", hover_each / G * 1000, "g", 0)
        if max_thrust > 0:
            twr = geometry.effective_thrust(max_thrust, frame) / weight
            r.value("Max thrust per motor", max_thrust, "N", 3)
            r.value("Thrust-to-weight", twr, ":1", 2)
            r.value("Hover throttle", 100.0 * hover_each / max_thrust, "%", 1)

        r.section("Commanded Demand")
        r.value("Roll", roll, "of hover thrust", 3)
        r.value("Pitch", pitch, "of hover thrust", 3)
        r.value("Yaw", yaw, "of hover thrust", 3)
        if frame.yaw_by_servo and abs(yaw) > 1e-9:
            r.blank()
            r.warn("A tricopter yaws by tilting its rear motor with a servo, "
                   "not by differential motor torque. The yaw demand does not "
                   "appear in the mixing below; size the tilt servo instead.")

        r.section("Per-Motor Thrust")
        table_rows = []
        saturated_high, saturated_low = [], []
        for row in rows:
            thrust = row["thrust"]
            fraction = row["fraction_of_hover"]
            flag = ""
            if thrust < 0:
                flag = "NEGATIVE"
                saturated_low.append(row["motor"])
            elif max_thrust > 0 and thrust > max_thrust:
                flag = "OVER MAX"
                saturated_high.append(row["motor"])
            throttle = (f"{100 * thrust / max_thrust:.0f}%"
                        if max_thrust > 0 else "-")
            table_rows.append([f"M{row['motor']}", f"arm {row['arm']}",
                               row["level"], row["spin"],
                               f"{thrust:.3f}", f"{thrust / G * 1000:.0f}",
                               f"{fraction:.2f}", throttle, flag])
        r.table(["Motor", "Arm", "Level", "Spin", "N", "grams", "x hover",
                 "throttle", ""], table_rows)

        # Raw motor thrust overstates the lift of a coaxial frame, because the
        # lower rotor of each pair works in the upper rotor's wash.
        total = sum(row["thrust"] for row in rows)
        lift = total * (1 - geometry.COAXIAL_PENALTY) if frame.coaxial else total
        r.blank()
        r.value("Total motor thrust", total, "N", 3)
        if frame.coaxial:
            r.value("Useful lift after coaxial loss", lift, "N", 3)
        r.value("Weight", weight, "N", 3)
        r.value("Vertical balance", lift / weight, "", 3)
        r.text("  A pure roll, pitch or yaw demand redistributes thrust without")
        r.text("  changing the total, so the aircraft holds altitude.")

        r.section("Moments")
        max_arm = max(abs(row["x"]) for row in rows) or arm
        roll_moment = sum(-row["y"] * row["thrust"] for row in rows)
        pitch_moment = sum(row["x"] * row["thrust"] for row in rows)
        r.value("Roll moment", roll_moment, "N.m", 4)
        r.value("Pitch moment", pitch_moment, "N.m", 4)
        if max_thrust > 0:
            available = (max_thrust - hover_each) * frame.arms * max_arm
            r.value("Approx. max roll moment available", available, "N.m", 4)

        r.section("Saturation Check")
        if saturated_high:
            r.warn(f"Motors {', '.join('M' + str(m) for m in saturated_high)} "
                   "exceed maximum thrust. The commanded attitude cannot be "
                   "achieved; the controller will clip and the aircraft will "
                   "respond less than demanded.")
        if saturated_low:
            r.warn(f"Motors {', '.join('M' + str(m) for m in saturated_low)} "
                   "are commanded below zero thrust. Fixed-pitch propellers "
                   "cannot pull downward, so authority is lost on that side.")
        if not saturated_high and not saturated_low:
            r.bullet("No motor saturates at this demand.")
            if max_thrust > 0:
                highest = max(row["thrust"] for row in rows)
                r.bullet(f"Peak motor sits at {100 * highest / max_thrust:.0f}% "
                         "of maximum thrust.")

        if max_thrust > 0:
            headroom = (max_thrust - hover_each) / hover_each
            r.blank()
            r.value("Control headroom above hover", headroom, "of hover", 3)
            r.text(f"  The largest single-axis demand this frame can hold")
            r.text(f"  without saturating is about {headroom:.2f} of hover thrust.")
            if headroom < 0.3:
                r.warn("Less than 0.3 of headroom leaves very little authority "
                       "for gusts. Aim for a thrust-to-weight of at least 2:1.")

        r.section("Layout Notes")
        r.text(f"  {frame.notes}")
        if frame.coaxial:
            r.bullet("Coaxial pairs counter-rotate on the same arm, so yaw "
                     "authority comes from the upper/lower split rather than "
                     "from opposite arms.")
        if frame.motors >= 6 and not frame.yaw_by_servo:
            r.bullet(f"With {frame.motors} motors this frame can usually "
                     "survive a single motor failure, though authority on that "
                     "axis is degraded.")

        figures = []
        if plotting.available():
            try:
                labels = [f"M{row['motor']}\n{row['thrust'] / G * 1000:.0f}g"
                          for row in rows[:len(frame.positions)]]
                figures.append(plotting.scatter_layout(
                    f"{layout_name} Thrust Distribution", frame.positions,
                    labels))
                figures.append(plotting.bar_chart(
                    "Per-Motor Thrust", "Thrust (N)", "",
                    [f"M{row['motor']}" for row in rows],
                    [row["thrust"] for row in rows]))
            except Exception:
                r.note("Charts could not be generated.")

        return report.result(r, outputs={
            "Hover Thrust per Motor": {"value": hover_each, "unit": "N"},
            "Peak Motor Thrust": {"value": max(row["thrust"] for row in rows),
                                  "unit": "N"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
