"""
CG, Neutral Point and Static Margin

The calculation an RC airframe most needs and the suite previously lacked
entirely. Locates the stick-fixed neutral point, reports the static margin for
a proposed CG, and gives the CG range that keeps the aircraft in a chosen
stability band. Handles conventional tailplanes, canards and tailless wings.

All longitudinal positions are measured aft from the wing root leading edge.
"""

import math

from uavlib import aero, geometry, report, units

TOOL_METADATA = {
    "name": "CG, Neutral Point & Static Margin",
    "category": "Fixed Wing / Stability",
    "description": (
        "Finds the neutral point and static margin, and reports the CG range "
        "for a target stability band. Positions are measured aft from the wing "
        "root leading edge. Static margin is the single best predictor of how "
        "an aeroplane will handle."
    ),
    "inputs": [
        {"key": "config", "label": "Configuration", "type": "choice",
         "choices": ["Conventional tail", "Canard", "Tailless / flying wing"],
         "default": "Conventional tail"},
        {"key": "wing_area", "label": "Wing Area (S)", "unit": "m^2", "type": "number"},
        {"key": "span", "label": "Wing Span (b)", "unit": "m", "type": "number"},
        {"key": "taper", "label": "Wing Taper Ratio", "type": "number",
         "default": "1.0", "min": 0.05, "max": 1.0},
        {"key": "sweep", "label": "Quarter-Chord Sweep", "unit": "deg",
         "type": "number", "default": "0"},
        {"key": "x_wing_le", "label": "Wing Root LE Position", "unit": "m",
         "type": "number", "default": "0",
         "help": "Datum. Leave at 0 to measure everything from the wing root "
                 "leading edge."},
        {"key": "tail_area", "label": "Tail / Canard Area", "unit": "m^2",
         "type": "number", "help": "Leave blank for a tailless wing."},
        {"key": "tail_arm", "label": "Tail Arm", "unit": "m", "type": "number",
         "help": "Wing quarter-chord to tail quarter-chord. Positive aft."},
        {"key": "tail_ar", "label": "Tail Aspect Ratio", "type": "number",
         "default": "4.0"},
        {"key": "tail_efficiency", "label": "Tail Efficiency", "type": "number",
         "default": "0.9",
         "help": "Dynamic pressure at the tail relative to free stream. 0.9 is "
                 "typical; a tail in the propeller wash can exceed 1."},
        {"key": "x_cg", "label": "Proposed CG Position", "unit": "m",
         "type": "number", "help": "Aft of the wing root LE. Blank to skip."},
        {"key": "target_sm", "label": "Target Static Margin", "unit": "fraction of MAC",
         "type": "number", "default": "0.15"},
    ],
}


def run(inputs):
    try:
        config = inputs.get("config") or "Conventional tail"
        wing_area = units.positive(inputs, "wing_area", "m^2", "Wing area")
        span = units.positive(inputs, "span", "m", "Wing span")
        taper = units.optional(inputs, "taper", "", 1.0) or 1.0
        sweep = units.optional(inputs, "sweep", "deg", 0.0)
        x_wing_le = units.optional(inputs, "x_wing_le", "m", 0.0)
        tail_area = units.optional(inputs, "tail_area", "m^2", 0.0)
        tail_arm = units.optional(inputs, "tail_arm", "m", 0.0)
        tail_ar = units.optional(inputs, "tail_ar", "", 4.0) or 4.0
        eta_tail = units.optional(inputs, "tail_efficiency", "", 0.9) or 0.9
        x_cg = units.parse(inputs.get("x_cg"), "m", None)
        target_sm = units.optional(inputs, "target_sm", "", 0.15)

        aspect_ratio = span ** 2 / wing_area
        wing = geometry.wing_from_area_ar(wing_area, aspect_ratio, taper, sweep)

        # The wing aerodynamic centre sits at the MAC quarter chord, which is
        # itself set back from the root LE by the sweep.
        x_ac_wing = x_wing_le + wing.x_mac_le + 0.25 * wing.mac
        a_wing = aero.lift_curve_slope_3d(aspect_ratio, sweep_qc_deg=sweep)

        tailless = config == "Tailless / flying wing" or tail_area <= 0 or tail_arm == 0
        is_canard = config == "Canard"

        r = report.Report("CG and Static Margin")
        r.section("Wing Geometry")
        r.value("Wing area (S)", wing_area, "m^2", 4)
        r.value("Span (b)", span, "m", 3)
        r.value("Aspect ratio", aspect_ratio, "", 2)
        r.value("MAC", wing.mac, "m", 4)
        r.value("MAC spanwise station", wing.y_mac, "m", 4)
        r.value("MAC LE aft of root LE", wing.x_mac_le, "m", 4)
        r.value("Wing lift slope", a_wing, "per rad", 3)
        r.value("Wing aerodynamic centre", x_ac_wing, "m aft of datum", 4)

        if tailless:
            # A tailless wing's neutral point is essentially its own AC; sweep
            # and washout provide the pitching moment instead of a tailplane.
            x_np = x_ac_wing
            r.section("Neutral Point (tailless)")
            r.value("Neutral point", x_np, "m aft of datum", 4)
            r.text("  With no tail the neutral point is the wing aerodynamic")
            r.text("  centre. Pitch stability comes from sweep combined with")
            r.text("  washout, or from a reflexed aerofoil.")
            r.warn("Flying wings need a smaller static margin than this tool's "
                   "default: 5-10% of MAC is normal, and more than 15% makes "
                   "them very reluctant to manoeuvre.")
        else:
            a_tail = aero.lift_curve_slope_3d(tail_ar)
            if is_canard:
                # A foreplane ahead of the wing moves the neutral point FORWARD,
                # which is why canards are so sensitive to CG.
                arm = -abs(tail_arm)
                downwash = 0.0  # the canard is in clean air
            else:
                arm = abs(tail_arm)
                downwash = aero.downwash_slope(aspect_ratio, a_wing)

            x_np = aero.neutral_point(
                x_ac_wing, wing.mac, wing_area, a_wing, a_tail, tail_area,
                arm, downwash, eta_tail)

            volume_coefficient = tail_area * abs(arm) / (wing_area * wing.mac)

            r.section("Tail Contribution" if not is_canard else "Canard Contribution")
            r.value("Surface area", tail_area, "m^2", 4)
            r.value("Arm", abs(tail_arm), "m", 3)
            r.value("Aspect ratio", tail_ar, "", 2)
            r.value("Lift slope", a_tail, "per rad", 3)
            r.value("Volume coefficient", volume_coefficient, "", 4)
            if not is_canard:
                r.value("Downwash slope (de/da)", downwash, "", 4)
            r.value("Efficiency (eta)", eta_tail, "", 2)

            r.section("Neutral Point")
            r.value("Neutral point", x_np, "m aft of datum", 4)
            r.value("As fraction of MAC", (x_np - x_wing_le - wing.x_mac_le) / wing.mac,
                    "of MAC aft of MAC LE", 4)
            if is_canard:
                r.text("  The canard shifts the neutral point FORWARD, so the CG")
                r.text("  must move forward with it. Canards tolerate very little")
                r.text("  CG error.")

        # CG envelope for the requested stability band.
        r.section("CG Envelope")
        x_cg_target = x_np - target_sm * wing.mac
        r.value(f"CG for {target_sm * 100:.0f}% static margin", x_cg_target,
                "m aft of datum", 4)
        mac_le = x_wing_le + wing.x_mac_le
        r.value("  as % of MAC", 100.0 * (x_cg_target - mac_le) / wing.mac, "%", 1)

        bands = [("Aerobatic / agile", 0.05), ("Sport", 0.10),
                 ("General / FPV", 0.15), ("Stable", 0.25), ("Trainer", 0.35)]
        rows = []
        for label, margin in bands:
            position = x_np - margin * wing.mac
            rows.append([label, f"{margin * 100:.0f}%", f"{position:.4f}",
                         f"{100.0 * (position - mac_le) / wing.mac:.1f}%"])
        r.blank()
        r.table(["Handling", "SM", "CG (m)", "% MAC"], rows)
        r.blank()
        r.text("  The aft limit is the neutral point itself; never fly there.")
        r.text("  The forward limit is set by elevator authority at the flare.")

        outputs = {
            "Mean Aerodynamic Chord": {"value": wing.mac, "unit": "m"},
            "Neutral Point": {"value": x_np, "unit": "m"},
            "Target CG Position": {"value": x_cg_target, "unit": "m"},
        }

        if x_cg is not None:
            sm = aero.static_margin(x_cg, x_np, wing.mac)
            r.section("Proposed CG")
            r.value("CG position", x_cg, "m aft of datum", 4)
            r.value("CG as % of MAC", 100.0 * (x_cg - mac_le) / wing.mac, "%", 1)
            r.value("Static margin", sm, "of MAC", 4)
            r.value("Static margin", sm * 100.0, "%", 1)
            r.blank()
            r.text(f"  {aero.static_margin_note(sm)}")
            if sm < 0:
                r.warn("The CG is BEHIND the neutral point. Move ballast "
                       f"forward by at least {(x_cg - x_np) * 1000:.0f} mm "
                       "before flying.")
            elif sm < 0.05:
                r.warn("Static margin below 5% leaves almost no tolerance for "
                       "build or payload variation.")
            outputs["Static Margin"] = {"value": sm}
            outputs["CG Position"] = {"value": x_cg, "unit": "m"}

        r.blank()
        r.text("  Static margin is measured in fractions of the MAC, so a short-")
        r.text("  chord wing needs the CG held to tighter absolute tolerance.")

        return report.result(r, outputs=outputs)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
