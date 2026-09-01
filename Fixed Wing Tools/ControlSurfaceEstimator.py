"""
Control Surface Authority, Hinge Moment and Servo Torque

Rewritten to correct two defects in an earlier version:

* The Glauert flap effectiveness formula returned values above 1.0. Tau is a
  fraction of a full angle-of-attack change and cannot exceed 1; the correct
  relation is tau = 1 - (theta - sin theta)/pi with theta = acos(2*cf/c - 1).
* Surface area was derived from the moment arm, and the chord fraction never
  entered the area at all. Area is now integrated between real inboard and
  outboard span stations.

It also answers the question a builder actually has: what servo do I need?
"""

import math

from uavlib import aero, atmosphere, report, units

TOOL_METADATA = {
    "name": "Control Surface Authority",
    "category": "Fixed Wing / Control",
    "description": (
        "Sizes ailerons, elevators and rudders. Computes flap effectiveness, "
        "control power, steady roll rate, hinge moment and the servo torque "
        "required. Guideline proportions: ailerons from 50-100% semi-span at "
        "20-30% chord; elevator and rudder full tail span at 25-40% chord."
    ),
    "inputs": [
        {"key": "surface", "label": "Surface Type", "type": "choice",
         "choices": ["Aileron", "Elevator", "Rudder"], "default": "Aileron"},
        {"key": "span", "label": "Wing / Tail Span (b)", "unit": "m", "type": "number",
         "help": "Full span of the surface this control lives on."},
        {"key": "area", "label": "Wing / Tail Area (S)", "unit": "m^2", "type": "number"},
        {"key": "root_chord", "label": "Root Chord", "unit": "m", "type": "number"},
        {"key": "taper", "label": "Taper Ratio", "type": "number", "default": "1.0",
         "min": 0.05, "max": 1.0},
        {"key": "y_inboard", "label": "Inboard Station", "unit": "m", "type": "number",
         "help": "From the centreline. For a full-span elevator use 0."},
        {"key": "y_outboard", "label": "Outboard Station", "unit": "m", "type": "number",
         "help": "From the centreline, out to at most half the span."},
        {"key": "chord_fraction", "label": "Surface Chord", "unit": "fraction of chord",
         "type": "number", "default": "0.25", "min": 0.05, "max": 0.6},
        {"key": "deflection", "label": "Max Deflection", "unit": "deg",
         "type": "number", "default": "20"},
        {"key": "velocity", "label": "Airspeed", "unit": "m/s", "type": "number",
         "help": "Use the highest speed the surface sees; hinge moment grows "
                 "with the square of speed."},
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number",
         "default": "0"},
        {"key": "horn_length", "label": "Control Horn Length", "unit": "mm",
         "type": "number", "default": "15",
         "help": "Hinge line to pushrod hole. Shorter horn means more travel "
                 "but more servo torque."},
    ],
}


def _surface_area(root_chord, taper, half_span, y1, y2, chord_fraction):
    """Planform area of the control surface itself, integrating the local chord.

    c(y) = c_root * (1 - (1 - taper) * y / (b/2)), so the area between two
    stations is the integral of chord_fraction * c(y) dy.
    """
    slope = (1.0 - taper) / half_span
    integral = root_chord * ((y2 - y1) - slope * (y2 ** 2 - y1 ** 2) / 2.0)
    return chord_fraction * integral


def run(inputs):
    try:
        surface = inputs.get("surface", "Aileron") or "Aileron"
        span = units.positive(inputs, "span", "m", "Span")
        area = units.positive(inputs, "area", "m^2", "Area")
        root_chord = units.positive(inputs, "root_chord", "m", "Root chord")
        taper = units.optional(inputs, "taper", "", 1.0) or 1.0
        y1 = units.optional(inputs, "y_inboard", "m", 0.0)
        y2 = units.positive(inputs, "y_outboard", "m", "Outboard station")
        cf_c = units.positive(inputs, "chord_fraction", "", "Surface chord fraction",
                              default=0.25)
        deflection = units.positive(inputs, "deflection", "deg", "Deflection",
                                    default=20.0)
        velocity = units.positive(inputs, "velocity", "m/s", "Airspeed")
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        horn = units.optional(inputs, "horn_length", "m", 0.015)

        half_span = span / 2.0
        if y2 > half_span + 1e-9:
            return report.error(
                f"Outboard station ({y2:.3f} m) is beyond the semi-span "
                f"({half_span:.3f} m).")
        if y2 <= y1:
            return report.error("Outboard station must be beyond the inboard station.")
        if cf_c > 0.6:
            return report.error("Surface chord fraction above 0.6 is outside the "
                                "range this theory covers.")

        aspect_ratio = span ** 2 / area
        air = atmosphere.at(altitude)
        q = 0.5 * air.density * velocity ** 2

        tau = aero.flap_effectiveness(cf_c)
        tau_inviscid = aero.flap_effectiveness(cf_c, viscous=False)
        lift_slope = aero.lift_curve_slope_3d(aspect_ratio)

        surf_area = _surface_area(root_chord, taper, half_span, y1, y2, cf_c)
        centroid = (y1 + y2) / 2.0
        mean_chord = surf_area / (y2 - y1) if y2 > y1 else 0.0

        r = report.Report(f"{surface} Authority")
        r.section("Geometry")
        r.value("Reference span", span, "m", 3)
        r.value("Reference area", area, "m^2", 4)
        r.value("Aspect ratio", aspect_ratio, "", 2)
        r.value("Surface span stations", f"{y1:.3f} to {y2:.3f}", "m")
        r.value("Surface span", y2 - y1, "m", 3)
        r.value("Fraction of semi-span", 100.0 * (y2 - y1) / half_span, "%", 1)
        r.value("Surface chord fraction", 100.0 * cf_c, "% of chord", 1)
        r.value("Surface area (one side)", surf_area, "m^2", 5)
        r.value("Surface mean chord", mean_chord, "m", 4)
        r.value("Area centroid", centroid, "m from centreline", 3)

        r.section("Aerodynamics")
        r.value("Air density", air.density, "kg/m^3", 4)
        r.value("Dynamic pressure (q)", q, "Pa", 1)
        r.value("Wing lift slope", lift_slope, "per rad", 3)
        r.value("Flap effectiveness (tau)", tau, "", 3,
                note=f"inviscid {tau_inviscid:.3f}")

        delta_rad = math.radians(deflection)

        if surface == "Aileron":
            cl_delta = aero.aileron_control_power(
                lift_slope, tau, span, root_chord, taper, y1, y2, area)
            cl_p = aero.roll_damping(lift_slope, aspect_ratio, taper)
            roll_rate_rad, pb_2v = aero.roll_rate(velocity, span, cl_delta,
                                                  cl_p, deflection)

            r.section("Roll Performance")
            r.value("Roll control power (Cl_da)", cl_delta, "per rad", 4)
            r.value("Roll damping (Cl_p)", cl_p, "per rad", 4)
            r.value("Helix angle (pb/2V)", pb_2v, "", 4)
            r.value("Steady roll rate", math.degrees(roll_rate_rad), "deg/s", 1)
            if roll_rate_rad > 0:
                r.value("Time for 360 deg roll", 2 * math.pi / roll_rate_rad, "s", 2)

            # pb/2V is the standard yardstick for roll authority.
            if pb_2v < 0.05:
                r.warn("Roll authority is low (pb/2V < 0.05). Enlarge the "
                       "ailerons or move them outboard.")
            elif pb_2v < 0.09:
                r.bullet("Adequate for a trainer or camera platform "
                         "(pb/2V 0.05-0.09).")
            elif pb_2v <= 0.20:
                r.bullet("Sporty and responsive (pb/2V 0.09-0.20).")
            else:
                r.bullet("Very high roll authority (pb/2V > 0.20), typical of "
                         "aerobatic models.")
            if y1 < 0.4 * half_span:
                r.warn("Ailerons starting inboard of 40% semi-span contribute "
                       "little roll for their area and drag.")
        else:
            # Elevator and rudder produce a moment about the CG through the
            # tail arm; report the force and the control derivative per degree.
            delta_cl = lift_slope * tau * delta_rad
            force = q * surf_area * delta_cl * (2.0 if y1 < 1e-6 else 1.0)
            r.section("Control Force")
            r.value("Lift coefficient change", delta_cl, "", 4)
            r.value("Force at full deflection", force, "N", 2)
            r.value("Force per degree", force / deflection, "N/deg", 3)
            r.bullet("Multiply by the tail arm to get the pitching or yawing "
                     "moment about the CG.")
            if cf_c < 0.25:
                r.warn(f"{surface} chord below 25% is usually too small; "
                       "30-40% is the normal range for models.")

        # Hinge moment and servo sizing -- what actually gets bought.
        ch = aero.hinge_moment_coefficient(cf_c, deflection)
        surface_chord = mean_chord if mean_chord > 0 else root_chord * cf_c
        hinge_moment = abs(ch) * q * surf_area * surface_chord
        horn = max(horn, 0.001)
        servo_force = hinge_moment / horn
        servo_torque = hinge_moment  # torque at the hinge equals servo torque
        # with a 1:1 horn ratio; scale by the horn/hinge lever ratio.

        r.section("Hinge Moment and Servo")
        r.value("Hinge moment coefficient", ch, "", 4)
        r.value("Hinge moment (one surface)", hinge_moment, "N.m", 4)
        r.value("Pushrod force", servo_force, "N", 2)
        r.dual("Servo torque needed", servo_torque, "N.m", "kg-cm", 3)
        recommended = servo_torque * 1.5
        r.dual("With 50% margin", recommended, "N.m", "kg-cm", 3)
        r.value("     also", units.nm_to_ozin(recommended), "oz-in", 1)

        r.blank()
        r.text("  Servo torque scales with airspeed squared: doubling speed")
        r.text("  quadruples the load. Size for the fastest dive, not cruise.")

        if velocity > 30:
            r.warn("At this airspeed control flutter is a real risk. Ensure "
                   "linkages are stiff and free of slop.")

        outputs = {
            "Flap Effectiveness (tau)": {"value": tau},
            f"{surface} Area": {"value": surf_area, "unit": "m^2"},
            f"{surface} Servo Torque": {"value": units.nm_to_kgcm(recommended),
                                        "unit": "kg-cm"},
        }
        if surface == "Aileron":
            outputs["Roll Rate"] = {"value": math.degrees(roll_rate_rad),
                                    "unit": "deg/s"}

        return report.result(r, outputs=outputs)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
