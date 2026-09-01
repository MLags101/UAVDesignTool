"""
Spiral Stability Parameter (B) Calculator

Corrects a units defect in an earlier version: the dihedral angle was converted
to radians before being compared against a threshold that is defined for
degrees. That made B about 57 times too small, so the tool reported
"spirally unstable" for every physically sensible aircraft.
"""

import math

from uavlib import report, units

TOOL_METADATA = {
    "name": "Spiral Stability Parameter",
    "category": "Fixed Wing / Stability",
    "description": (
        "Computes the spiral stability parameter B = (Lv * dihedral) / (b * CL), "
        "with dihedral in DEGREES. B >= 5 indicates the aircraft will roll its "
        "wings level on its own. Also solves backwards for the dihedral needed "
        "to reach a target B."
    ),
    "inputs": [
        {"key": "l_v", "label": "Vertical Tail Arm (Lv)", "unit": "m", "type": "number",
         "help": "Wing quarter-chord to vertical tail quarter-chord."},
        {"key": "dihedral", "label": "Dihedral Angle", "unit": "deg", "type": "number",
         "help": "Per panel, measured from horizontal. Polyhedral: use the "
                 "equivalent average."},
        {"key": "span", "label": "Wing Span (b)", "unit": "m", "type": "number"},
        {"key": "cl", "label": "Cruise Lift Coefficient (CL)", "type": "number",
         "default": "0.4",
         "help": "Spiral stability is worst at low speed, where CL is high."},
        {"key": "target_b", "label": "Target B", "type": "number", "default": "5",
         "help": "5 is the classic threshold for inherent spiral stability."},
    ],
}

TARGET_DEFAULT = 5.0


def run(inputs):
    try:
        lv = units.positive(inputs, "l_v", "m", "Vertical tail arm")
        dihedral_deg = units.optional(inputs, "dihedral", "deg", 0.0)
        span = units.positive(inputs, "span", "m", "Wing span")
        cl = units.positive(inputs, "cl", "", "Lift coefficient", default=0.4)
        target = units.optional(inputs, "target_b", "", TARGET_DEFAULT) or TARGET_DEFAULT

        # B uses dihedral in DEGREES. This is the whole point of the fix: the
        # threshold of 5 comes from correlations expressed in degrees.
        b_param = (lv * dihedral_deg) / (span * cl)

        r = report.Report("Spiral Stability")
        r.section("Inputs")
        r.value("Vertical tail arm (Lv)", lv, "m")
        r.value("Dihedral", dihedral_deg, "deg", 2)
        r.value("Wing span (b)", span, "m")
        r.value("Lift coefficient (CL)", cl, "", 3)
        r.value("Tail arm ratio (Lv/b)", lv / span, "", 3)

        r.section("Result")
        r.value("Spiral parameter B", b_param, "", 2)

        if b_param >= target:
            r.text(f"  SPIRALLY STABLE (B >= {target:g}).")
            r.text("  The aircraft tends to roll its wings level unaided.")
        else:
            r.text(f"  SPIRALLY UNSTABLE (B < {target:g}).")
            r.text("  Bank angle will slowly steepen if left untrimmed. This is")
            r.text("  flyable and common, but demands continuous pilot attention.")

        # Solve backwards for what would fix it.
        r.section(f"To reach B = {target:g}")
        needed_dihedral = target * span * cl / lv
        r.value("Required dihedral", needed_dihedral, "deg", 2)
        if needed_dihedral > dihedral_deg:
            r.value("Additional dihedral needed", needed_dihedral - dihedral_deg, "deg", 2)
        needed_arm = target * span * cl / dihedral_deg if dihedral_deg > 0 else float("inf")
        if math.isfinite(needed_arm):
            r.value("or required tail arm", needed_arm, "m", 3)

        if needed_dihedral > 12.0:
            r.warn("More than 12 degrees of dihedral is a lot; lengthening the "
                   "tail arm or enlarging the fin is usually the better fix.")

        r.section("Interpretation")
        if b_param > 10:
            r.bullet("Very stable, at the cost of strong dihedral effect. Expect "
                     "marked Dutch roll and sluggish roll response.")
        elif b_param >= 5:
            r.bullet("Well inside the stable range. Typical of trainers and "
                     "gliders that must self-recover.")
        elif b_param >= 3:
            r.bullet("Mildly unstable. Normal for sport and aerobatic models, "
                     "which trade self-levelling for roll authority.")
        else:
            r.bullet("Strongly spiral-unstable. Acceptable only with active "
                     "stabilisation or constant pilot input.")

        r.blank()
        r.text("  Spiral and Dutch roll pull in opposite directions: dihedral")
        r.text("  that fixes the spiral mode worsens Dutch roll. B of 5 is a")
        r.text("  compromise, not an optimum.")

        return report.result(r, outputs={
            "Spiral Parameter B": {"value": b_param},
            "Dihedral Angle": {"value": dihedral_deg, "unit": "deg"},
        })

    except units.UnitError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
