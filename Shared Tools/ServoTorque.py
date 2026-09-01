"""
Servo Torque and Linkage Sizing

Turns a control surface's hinge moment into the servo torque actually needed,
accounting for horn and arm geometry. The mechanical advantage of the linkage
is the part builders most often get wrong: a short control horn multiplies the
load on the servo, and hinge moment rises with the square of airspeed, so a
servo sized at cruise can stall in a dive.
"""

import math

from uavlib import aero, atmosphere, report, units

TOOL_METADATA = {
    "name": "Servo Torque & Linkage",
    "category": "Shared / Control",
    "description": (
        "Required servo torque from control surface geometry and airspeed, "
        "with the linkage ratio, deflection achieved and a recommended servo "
        "rating. Also converts between kg-cm, oz-in and N.m."
    ),
    "inputs": [
        {"key": "surface_area", "label": "Control Surface Area", "unit": "m^2",
         "type": "number", "help": "One surface, from the Control Authority tool."},
        {"key": "surface_chord", "label": "Surface Mean Chord", "unit": "m",
         "type": "number"},
        {"key": "chord_fraction", "label": "Surface Chord Fraction",
         "type": "number", "default": "0.25", "min": 0.05, "max": 0.6,
         "help": "Surface chord divided by the total chord at that station."},
        {"key": "deflection", "label": "Max Deflection", "unit": "deg",
         "type": "number", "default": "25"},
        {"key": "velocity", "label": "Maximum Airspeed", "unit": "m/s",
         "type": "number", "help": "Use the dive speed, not cruise."},
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number",
         "default": "0"},
        {"key": "horn_length", "label": "Control Horn Length", "unit": "m",
         "type": "number", "default": "15 mm",
         "help": "Hinge line to pushrod hole on the surface."},
        {"key": "servo_arm", "label": "Servo Arm Length", "unit": "m",
         "type": "number", "default": "12 mm",
         "help": "Servo output shaft to pushrod hole."},
        {"key": "servo_travel", "label": "Servo Travel", "unit": "deg",
         "type": "number", "default": "60",
         "help": "Rotation available each way, typically 45-60 degrees."},
        {"key": "aerodynamic_balance", "label": "Aerodynamic Balance",
         "type": "choice",
         "choices": ["None (plain hinge)", "Sealed gap", "Horn balanced"],
         "default": "None (plain hinge)"},
        {"key": "friction_allowance", "label": "Friction Allowance", "unit": "%",
         "type": "number", "default": "25",
         "help": "Covers hinge stiffness, linkage friction and control slop."},
    ],
}

# A sealed hinge gap or an aerodynamic horn reduces hinge moment considerably.
BALANCE_FACTOR = {
    "None (plain hinge)": 1.0,
    "Sealed gap": 0.85,
    "Horn balanced": 0.60,
}

# Common hobby servo classes for the recommendation table.
SERVO_CLASSES = [
    (0.6, "Micro (3.7 g class)"),
    (1.8, "Sub-micro (9 g class)"),
    (3.5, "Standard micro (like HS-55)"),
    (6.0, "Standard (like HS-311)"),
    (11.0, "Standard high torque"),
    (20.0, "Quarter-scale / digital"),
    (35.0, "Large scale"),
    (float("inf"), "Giant scale / industrial"),
]


def run(inputs):
    try:
        area = units.positive(inputs, "surface_area", "m^2", "Surface area")
        chord = units.positive(inputs, "surface_chord", "m", "Surface chord")
        cf_c = units.positive(inputs, "chord_fraction", "", "Chord fraction",
                              default=0.25)
        deflection = units.positive(inputs, "deflection", "deg", "Deflection",
                                    default=25.0)
        velocity = units.positive(inputs, "velocity", "m/s", "Airspeed")
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        horn = units.positive(inputs, "horn_length", "m", "Horn length",
                              default=0.015)
        servo_arm = units.positive(inputs, "servo_arm", "m", "Servo arm",
                                   default=0.012)
        servo_travel = units.positive(inputs, "servo_travel", "deg",
                                      "Servo travel", default=60.0)
        balance = inputs.get("aerodynamic_balance") or "None (plain hinge)"
        friction = units.fraction(inputs, "friction_allowance", 0.25)

        air = atmosphere.at(altitude)
        q = 0.5 * air.density * velocity ** 2

        ch = aero.hinge_moment_coefficient(cf_c, deflection)
        balance_factor = BALANCE_FACTOR.get(balance, 1.0)
        hinge_moment = abs(ch) * q * area * chord * balance_factor

        pushrod_force = hinge_moment / horn
        servo_torque = pushrod_force * servo_arm
        with_friction = servo_torque * (1.0 + friction)
        recommended = with_friction * 1.5  # design margin on top

        linkage_ratio = servo_arm / horn
        achieved_deflection = servo_travel * linkage_ratio

        r = report.Report("Servo Torque & Linkage")
        r.section("Aerodynamic Load")
        r.dual("Airspeed", velocity, "m/s", "mph", 2)
        r.value("Air density", air.density, "kg/m^3", 4)
        r.value("Dynamic pressure", q, "Pa", 1)
        r.value("Surface area", area, "m^2", 5)
        r.value("Surface mean chord", chord, "m", 4)
        r.value("Chord fraction", cf_c, "", 3)
        r.value("Deflection", deflection, "deg", 1)
        r.value("Hinge moment coefficient", ch, "", 4)
        r.value("Aerodynamic balance", balance,
                note=f"factor {balance_factor:.2f}")
        r.value("Hinge moment", hinge_moment, "N.m", 4)

        r.section("Linkage")
        r.dual("Control horn length", horn, "m", "in", 4)
        r.dual("Servo arm length", servo_arm, "m", "in", 4)
        r.value("Linkage ratio (arm/horn)", linkage_ratio, "", 3)
        r.value("Pushrod force", pushrod_force, "N", 2)
        r.value("Servo travel available", servo_travel, "deg", 1)
        r.value("Surface deflection achieved", achieved_deflection, "deg", 1)

        if achieved_deflection < deflection * 0.95:
            r.warn(f"This linkage reaches only {achieved_deflection:.0f} deg of "
                   f"surface deflection against the {deflection:.0f} deg wanted. "
                   "Use a longer servo arm or a shorter control horn.")
        elif achieved_deflection > deflection * 1.6:
            r.bullet("Far more travel than needed. Shortening the servo arm "
                     "would reduce torque demand and improve resolution.")

        r.section("Servo Requirement")
        r.value("Torque at the servo", servo_torque, "N.m", 4)
        r.value("Plus friction allowance", with_friction, "N.m", 4,
                note=f"+{friction * 100:.0f}%")
        r.value("Recommended rating", recommended, "N.m", 4, note="+50% margin")
        r.blank()
        r.value("Recommended servo", units.nm_to_kgcm(recommended), "kg-cm", 2)
        r.value("  also", units.nm_to_ozin(recommended), "oz-in", 1)
        r.value("  also", recommended, "N.m", 4)

        servo_class = next(label for limit, label in SERVO_CLASSES
                           if units.nm_to_kgcm(recommended) <= limit)
        r.value("Servo class", servo_class)

        r.section("Speed Sensitivity")
        r.text("  Hinge moment scales with the square of airspeed, so a servo")
        r.text("  chosen for cruise can stall in a dive:")
        r.blank()
        rows = []
        for factor in (0.5, 0.75, 1.0, 1.25, 1.5):
            v = velocity * factor
            q_v = 0.5 * air.density * v ** 2
            moment = abs(ch) * q_v * area * chord * balance_factor
            torque = moment / horn * servo_arm * (1 + friction) * 1.5
            rows.append([f"{v:.1f}", f"{units.ms_to_mph(v):.0f}",
                         f"{moment:.4f}", f"{units.nm_to_kgcm(torque):.2f}",
                         "<-- design" if abs(factor - 1.0) < 1e-9 else ""])
        r.table(["V m/s", "V mph", "Hinge N.m", "Servo kg-cm", ""], rows)

        r.section("Notes")
        r.bullet("Digital servos hold position against load far better than "
                 "analogue ones, at the cost of higher current draw.")
        r.bullet("A sealed hinge gap cuts hinge moment by roughly 15% and "
                 "improves control effectiveness at the same time.")
        if linkage_ratio > 1.5:
            r.warn("The servo arm is much longer than the control horn, which "
                   "multiplies the torque the servo must produce. Lengthen the "
                   "horn instead.")
        r.bullet("Size for the fastest speed the model will ever see, "
                 "including a vertical dive, not for cruise.")

        return report.result(r, outputs={
            "Hinge Moment": {"value": hinge_moment, "unit": "N.m"},
            "Servo Torque Required": {"value": units.nm_to_kgcm(recommended),
                                      "unit": "kg-cm"},
            "Pushrod Force": {"value": pushrod_force, "unit": "N"},
        })

    except units.UnitError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
