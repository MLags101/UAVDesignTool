"""
Dynamic Stability Modes

Approximate frequencies and damping of the four classical modes: short period
and phugoid in pitch, Dutch roll and roll subsidence laterally. These are
handling-quality estimates from conceptual-design approximations, not a
substitute for a proper linearised model, but they answer the practical
questions -- will it porpoise, will it wallow, will it wag its tail.

The recurring trade-off: dihedral that fixes the spiral mode makes Dutch roll
worse, and a bigger fin that fixes Dutch roll makes the spiral mode worse.
"""

import math

from uavlib import aero, atmosphere, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Dynamic Stability Modes",
    "category": "Fixed Wing / Stability",
    "description": (
        "Short period, phugoid, Dutch roll and roll subsidence estimates with "
        "handling-quality assessment. Uses the standard conceptual-design "
        "approximations."
    ),
    "inputs": [
        {"key": "mass", "label": "Total Mass", "unit": "kg", "type": "number"},
        {"key": "wing_area", "label": "Wing Area (S)", "unit": "m^2",
         "type": "number"},
        {"key": "span", "label": "Wing Span (b)", "unit": "m", "type": "number"},
        {"key": "mac", "label": "Mean Aerodynamic Chord", "unit": "m",
         "type": "number"},
        {"key": "velocity", "label": "Flight Speed", "unit": "m/s",
         "type": "number"},
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number",
         "default": "0"},
        {"key": "static_margin", "label": "Static Margin", "unit": "fraction of MAC",
         "type": "number", "default": "0.15"},
        {"key": "iyy", "label": "Pitch Inertia (Iyy)", "unit": "kg.m^2",
         "type": "number", "help": "From the Mass Properties tool."},
        {"key": "ixx", "label": "Roll Inertia (Ixx)", "unit": "kg.m^2",
         "type": "number"},
        {"key": "izz", "label": "Yaw Inertia (Izz)", "unit": "kg.m^2",
         "type": "number"},
        {"key": "tail_volume_h", "label": "Horizontal Tail Volume (Vh)",
         "type": "number", "default": "0.5"},
        {"key": "tail_volume_v", "label": "Vertical Tail Volume (Vv)",
         "type": "number", "default": "0.04"},
        {"key": "dihedral", "label": "Dihedral", "unit": "deg", "type": "number",
         "default": "3"},
        {"key": "cd0", "label": "Parasite Drag (CD0)", "type": "number",
         "default": "0.035"},
    ],
}


def damping_note(zeta):
    if zeta < 0:
        return "DIVERGENT -- the oscillation grows. Not acceptable."
    if zeta < 0.1:
        return "Very lightly damped; oscillations persist for many cycles."
    if zeta < 0.3:
        return "Lightly damped but acceptable for a model."
    if zeta < 0.8:
        return "Well damped. This is the comfortable range."
    if zeta < 1.0:
        return "Heavily damped; response will feel sluggish."
    return "Overdamped -- no oscillation, just a slow return."


def run(inputs):
    try:
        mass = units.positive(inputs, "mass", "kg", "Mass")
        wing_area = units.positive(inputs, "wing_area", "m^2", "Wing area")
        span = units.positive(inputs, "span", "m", "Span")
        mac = units.positive(inputs, "mac", "m", "MAC")
        velocity = units.positive(inputs, "velocity", "m/s", "Flight speed")
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        static_margin = units.optional(inputs, "static_margin", "", 0.15)
        cd0 = units.positive(inputs, "cd0", "", "CD0", default=0.035)
        vh = units.optional(inputs, "tail_volume_h", "", 0.5) or 0.5
        vv = units.optional(inputs, "tail_volume_v", "", 0.04) or 0.04
        dihedral = units.optional(inputs, "dihedral", "deg", 3.0)

        air = atmosphere.at(altitude)
        q = 0.5 * air.density * velocity ** 2
        weight = mass * G
        aspect_ratio = span ** 2 / wing_area
        lift_slope = aero.lift_curve_slope_3d(aspect_ratio)
        oswald = aero.oswald_efficiency(aspect_ratio)
        k = aero.induced_drag_factor(aspect_ratio, oswald)
        cl = aero.cl_required(mass, wing_area, velocity, altitude)

        # Default inertias from radius-of-gyration rules of thumb when the
        # Mass Properties tool has not been run.
        iyy = units.optional(inputs, "iyy", "", 0.0) or mass * (0.30 * mac * 3) ** 2
        ixx = units.optional(inputs, "ixx", "", 0.0) or mass * (0.20 * span / 2) ** 2
        izz = units.optional(inputs, "izz", "", 0.0) or (ixx + iyy)

        r = report.Report("Dynamic Stability")
        r.section("Flight Condition")
        r.dual("Speed", velocity, "m/s", "mph", 2)
        r.value("Altitude", altitude, "m", 0)
        r.value("Dynamic pressure", q, "Pa", 1)
        r.value("Lift coefficient", cl, "", 3)
        r.value("Static margin", static_margin * 100, "% MAC", 1)
        r.value("Lift-curve slope", lift_slope, "per rad", 3)
        r.value("Pitch inertia Iyy", iyy, "kg.m^2", 5)
        r.value("Roll inertia Ixx", ixx, "kg.m^2", 5)
        r.value("Yaw inertia Izz", izz, "kg.m^2", 5)

        # ---------------------------------------------------------- phugoid
        # Lanchester's approximation: a slow exchange of speed and height,
        # essentially independent of the aircraft's details.
        phugoid_omega = G * math.sqrt(2.0) / velocity
        phugoid_period = 2 * math.pi / phugoid_omega
        ld = cl / aero.drag_polar(cl, cd0, k)
        phugoid_zeta = 1.0 / (math.sqrt(2.0) * ld)

        r.section("Phugoid (long-period pitch)")
        r.value("Period", phugoid_period, "s", 2)
        r.value("Frequency", phugoid_omega / (2 * math.pi), "Hz", 4)
        r.value("Damping ratio", phugoid_zeta, "", 4)
        r.value("Time to half amplitude",
                0.693 / (phugoid_zeta * phugoid_omega)
                if phugoid_zeta * phugoid_omega > 0 else float("inf"), "s", 1)
        r.text(f"  {damping_note(phugoid_zeta)}")
        r.text("  A slow speed-and-height exchange. Lightly damped is normal")
        r.text("  and easy to fly through; the pilot corrects it without")
        r.text("  noticing. Damping improves with L/D.")

        # ----------------------------------------------------- short period
        # Fast pitch oscillation, driven by static margin and tail damping.
        cm_alpha = -static_margin * lift_slope
        cm_q = -2.0 * vh * lift_slope  # tail pitch damping
        m_alpha = q * wing_area * mac * cm_alpha / iyy
        m_q = q * wing_area * mac ** 2 * cm_q / (2.0 * velocity * iyy)
        z_alpha = -q * wing_area * lift_slope / (mass * velocity)

        sp_omega_squared = max(1e-9, m_alpha * -1.0 + z_alpha * m_q)
        sp_omega = math.sqrt(sp_omega_squared)
        sp_zeta = -(m_q + z_alpha) / (2.0 * sp_omega) if sp_omega > 0 else 0.0

        r.section("Short Period (fast pitch)")
        r.value("Natural frequency", sp_omega, "rad/s", 3)
        r.value("  in Hz", sp_omega / (2 * math.pi), "Hz", 3)
        r.value("Period", 2 * math.pi / sp_omega if sp_omega > 0 else 0, "s", 3)
        r.value("Damping ratio", sp_zeta, "", 4)
        r.value("Cm_alpha", cm_alpha, "per rad", 4)
        r.text(f"  {damping_note(sp_zeta)}")
        if sp_zeta < 0.3:
            r.warn("Short-period damping below 0.3 makes the model feel "
                   "twitchy and prone to pilot-induced oscillation. A larger "
                   "tail or a longer tail arm helps.")
        if sp_omega > 30:
            r.bullet("A high short-period frequency is normal for a small "
                     "model; it is what makes them feel quick compared with "
                     "full-scale aircraft.")

        # -------------------------------------------------------- Dutch roll
        # Yaw-roll oscillation. Fin volume drives stiffness, dihedral the roll
        # coupling that makes it objectionable.
        cn_beta = vv * lift_slope * 0.9
        cn_r = -2.0 * vv * lift_slope * 0.9
        n_beta = q * wing_area * span * cn_beta / izz
        n_r = q * wing_area * span ** 2 * cn_r / (2.0 * velocity * izz)

        dr_omega = math.sqrt(max(1e-9, n_beta))
        dr_zeta = -n_r / (2.0 * dr_omega) if dr_omega > 0 else 0.0
        # Dihedral worsens Dutch roll by feeding sideslip into roll.
        cl_beta = -abs(math.radians(dihedral)) * lift_slope / 4.0
        dr_zeta_effective = max(0.0, dr_zeta * (1.0 - min(0.6, abs(cl_beta))))

        r.section("Dutch Roll (yaw-roll oscillation)")
        r.value("Natural frequency", dr_omega, "rad/s", 3)
        r.value("Period", 2 * math.pi / dr_omega if dr_omega > 0 else 0, "s", 3)
        r.value("Damping ratio (yaw only)", dr_zeta, "", 4)
        r.value("Damping with dihedral coupling", dr_zeta_effective, "", 4)
        r.value("Cn_beta (weathercock)", cn_beta, "per rad", 4)
        r.value("Cl_beta (dihedral effect)", cl_beta, "per rad", 4)
        r.text(f"  {damping_note(dr_zeta_effective)}")
        if dr_zeta_effective < 0.08:
            r.warn("Dutch roll is very lightly damped: the model will wallow "
                   "and wag its tail in turbulence. Increase fin area or "
                   "reduce dihedral.")
        if abs(cl_beta) > abs(cn_beta) * 2:
            r.warn("Dihedral effect greatly exceeds directional stiffness. "
                   "This is the classic recipe for objectionable Dutch roll.")

        # ---------------------------------------------------- roll subsidence
        cl_p = aero.roll_damping(lift_slope, aspect_ratio)
        l_p = q * wing_area * span ** 2 * cl_p / (2.0 * velocity * ixx)
        roll_tau = -1.0 / l_p if l_p < 0 else float("inf")

        r.section("Roll Subsidence")
        r.value("Roll damping Cl_p", cl_p, "per rad", 4)
        r.value("Roll time constant", roll_tau, "s", 4)
        r.value("Time to 63% of steady roll rate", roll_tau, "s", 4)
        if roll_tau < 0.1:
            r.bullet("Very quick roll response, typical of a small aerobatic "
                     "model.")
        elif roll_tau < 0.4:
            r.bullet("Crisp roll response.")
        else:
            r.warn("Slow roll response. A large roll inertia relative to the "
                   "wing's damping makes the model feel heavy in roll.")

        r.section("Summary")
        r.table(["Mode", "Period s", "Damping", "Assessment"], [
            ["Phugoid", f"{phugoid_period:.1f}", f"{phugoid_zeta:.3f}",
             "acceptable" if phugoid_zeta > 0 else "divergent"],
            ["Short period",
             f"{2 * math.pi / sp_omega:.3f}" if sp_omega > 0 else "-",
             f"{sp_zeta:.3f}",
             "good" if sp_zeta > 0.3 else "twitchy"],
            ["Dutch roll",
             f"{2 * math.pi / dr_omega:.2f}" if dr_omega > 0 else "-",
             f"{dr_zeta_effective:.3f}",
             "good" if dr_zeta_effective > 0.08 else "wallows"],
            ["Roll", f"{roll_tau:.3f}", "-",
             "crisp" if roll_tau < 0.4 else "slow"],
        ])

        r.blank()
        r.text("  These are conceptual-design approximations. They rank designs")
        r.text("  and catch obvious problems, but absolute values carry real")
        r.text("  uncertainty -- particularly the inertias, which dominate the")
        r.text("  short-period and Dutch-roll results.")
        r.bullet("Dihedral and fin area pull the spiral and Dutch roll modes in "
                 "opposite directions. Check both this tool and the Spiral "
                 "Stability tool before settling on either.")

        return report.result(r, outputs={
            "Phugoid Period": {"value": phugoid_period, "unit": "s"},
            "Short Period Damping": {"value": sp_zeta},
            "Dutch Roll Damping": {"value": dr_zeta_effective},
            "Roll Time Constant": {"value": roll_tau, "unit": "s"},
        })

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
