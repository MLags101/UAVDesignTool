"""
Wing Geometry Calculator

Turns area, aspect ratio, taper and sweep into the dimensions needed to draw
the wing, including the MAC position used to mark the CG. Adds wetted area,
Oswald efficiency and tip Reynolds number, and guards the zero-input case that
previously divided by zero.
"""

import math

from uavlib import aero, atmosphere, geometry, report, units

TOOL_METADATA = {
    "name": "Wing Geometry Calculator",
    "category": "Fixed Wing / Geometry",
    "description": (
        "Computes span, chords, MAC and its position, sweep angles and the tip "
        "leading-edge offset for CAD. Also reports wetted area, Oswald "
        "efficiency and Reynolds number at root and tip."
    ),
    "inputs": [
        {"key": "mode", "label": "Define Wing By", "type": "choice",
         "choices": ["Area and aspect ratio", "Span and root chord"],
         "default": "Area and aspect ratio"},
        {"key": "area", "label": "Planform Area (S)", "unit": "m^2", "type": "number"},
        {"key": "aspect_ratio", "label": "Aspect Ratio (AR)", "type": "number",
         "default": "8"},
        {"key": "span", "label": "Span (b)", "unit": "m", "type": "number",
         "help": "Used in 'Span and root chord' mode."},
        {"key": "root_chord", "label": "Root Chord", "unit": "m", "type": "number",
         "help": "Used in 'Span and root chord' mode."},
        {"key": "taper_ratio", "label": "Taper Ratio", "type": "number",
         "default": "1.0", "min": 0.05, "max": 1.0,
         "help": "Tip chord divided by root chord. 1.0 is rectangular."},
        {"key": "sweep_deg", "label": "Quarter-Chord Sweep", "unit": "deg",
         "type": "number", "default": "0"},
        {"key": "dihedral", "label": "Dihedral", "unit": "deg", "type": "number",
         "default": "0"},
        {"key": "thickness", "label": "Thickness Ratio (t/c)", "type": "number",
         "default": "0.12"},
        {"key": "velocity", "label": "Reference Speed", "unit": "m/s",
         "type": "number", "help": "Optional, for Reynolds numbers."},
    ],
}


def run(inputs):
    try:
        mode = inputs.get("mode") or "Area and aspect ratio"
        taper = units.optional(inputs, "taper_ratio", "", 1.0) or 1.0
        sweep = units.optional(inputs, "sweep_deg", "deg", 0.0)
        dihedral = units.optional(inputs, "dihedral", "deg", 0.0)
        thickness = units.optional(inputs, "thickness", "", 0.12) or 0.12
        velocity = units.optional(inputs, "velocity", "m/s", 0.0)

        if mode == "Span and root chord":
            span_in = units.positive(inputs, "span", "m", "Span")
            root_in = units.positive(inputs, "root_chord", "m", "Root chord")
            wing = geometry.wing_from_span_chord(span_in, root_in, taper, sweep)
        else:
            area = units.positive(inputs, "area", "m^2", "Planform area")
            aspect_ratio = units.positive(inputs, "aspect_ratio", "",
                                          "Aspect ratio", default=8.0)
            wing = geometry.wing_from_area_ar(area, aspect_ratio, taper, sweep)

        r = report.Report("Wing Geometry")
        r.section("Planform")
        r.dual("Planform area (S)", wing.area, "m^2", "ft^2", 4)
        r.dual("Span (b)", wing.span, "m", "in", 4)
        r.value("Aspect ratio", wing.aspect_ratio, "", 3)
        r.value("Taper ratio", wing.taper, "", 3)
        r.dual("Root chord", wing.root_chord, "m", "in", 4)
        r.dual("Tip chord", wing.tip_chord, "m", "in", 4)
        r.dual("Geometric mean chord (S/b)", wing.mean_chord, "m", "in", 4)

        r.section("Mean Aerodynamic Chord")
        r.dual("MAC length", wing.mac, "m", "in", 4)
        r.dual("MAC spanwise station", wing.y_mac, "m", "in", 4)
        r.dual("MAC LE aft of root LE", wing.x_mac_le, "m", "in", 4)
        r.dual("MAC quarter chord", wing.x_mac_le + 0.25 * wing.mac, "m", "in", 4)
        r.text("  Mark the CG relative to the MAC quarter chord, not the root.")

        r.section("Sweep and Layout")
        r.value("Quarter-chord sweep", wing.sweep_qc_deg, "deg", 2)
        r.value("Leading-edge sweep", wing.sweep_le_deg, "deg", 2)
        r.dual("Tip LE offset aft of root LE", wing.tip_le_lag, "m", "in", 4)
        r.value("Dihedral", dihedral, "deg", 2)
        if dihedral != 0:
            half_span = wing.span / 2.0
            rise = half_span * math.tan(math.radians(dihedral))
            r.dual("Tip rise from dihedral", rise, "m", "in", 4)
            r.dual("Projected span", wing.span * math.cos(math.radians(dihedral)),
                   "m", "in", 4)
        r.text("  Tip LE offset is how far back to move the tip rib in CAD.")

        r.section("Aerodynamic Properties")
        oswald = aero.oswald_efficiency(wing.aspect_ratio, sweep)
        lift_slope = aero.lift_curve_slope_3d(wing.aspect_ratio, sweep_qc_deg=sweep)
        r.value("Wetted area (both sides)", wing.wetted_area(thickness), "m^2", 4)
        r.value("Oswald efficiency (e)", oswald, "", 3)
        r.value("Induced drag factor (k)",
                aero.induced_drag_factor(wing.aspect_ratio, oswald), "", 5)
        r.value("Lift-curve slope", lift_slope, "per rad", 3)
        r.value("  per degree", math.radians(1) * lift_slope, "", 5)
        r.note(aero.oswald_note(wing.aspect_ratio))

        if velocity > 0:
            r.section("Reynolds Numbers")
            rows = []
            for label, chord in (("Root", wing.root_chord), ("MAC", wing.mac),
                                 ("Tip", wing.tip_chord)):
                rows.append([label, f"{chord:.4f}",
                             f"{atmosphere.reynolds(velocity, chord):,.0f}"])
            r.table(["Station", "Chord m", "Re"], rows)
            tip_re = atmosphere.reynolds(velocity, wing.tip_chord)
            if tip_re < 70_000:
                r.warn("Tip Reynolds number is very low. The tip will stall "
                       "before the root, dropping a wing. Add washout or "
                       "reduce taper.")

        r.section("Notes")
        if wing.taper < 0.4:
            r.warn(f"Taper of {wing.taper:.2f} concentrates lift outboard and "
                   "promotes tip stall. Below 0.4 washout is effectively "
                   "mandatory.")
        elif 0.4 <= wing.taper <= 0.6:
            r.bullet("Taper in the 0.4-0.6 range approximates an elliptical "
                     "lift distribution well and is a good default.")
        if wing.aspect_ratio > 12:
            r.bullet("High aspect ratio gives low induced drag but needs a "
                     "stiffer spar; check the Spar Sizing tool.")
        elif wing.aspect_ratio < 5:
            r.bullet("Low aspect ratio is draggy in the induced term but very "
                     "strong and manoeuvrable.")

        return report.result(r, outputs={
            "Wing Area (S)": {"value": wing.area, "unit": "m^2"},
            "Wing Span (b)": {"value": wing.span, "unit": "m"},
            "Root Chord": {"value": wing.root_chord, "unit": "m"},
            "Tip Chord": {"value": wing.tip_chord, "unit": "m"},
            "Mean Aerodynamic Chord": {"value": wing.mac, "unit": "m"},
            "Aspect Ratio": {"value": wing.aspect_ratio},
        })

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
