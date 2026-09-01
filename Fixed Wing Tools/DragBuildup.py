"""
Component Drag Buildup and Drag Polar

Estimates CD0 by adding up each component's wetted-area skin friction with a
form factor, then assembles the full polar CD = CD0 + k*CL^2. Everything
downstream -- range, endurance, glide, best-climb speed -- depends on this
polar, which is why guessing a single Cl/Cd pair is such a weak substitute.
"""

import math

from uavlib import aero, atmosphere, plotting, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Drag Buildup & Polar",
    "category": "Fixed Wing / Aerodynamics",
    "description": (
        "Builds CD0 from component wetted areas and form factors, then reports "
        "the drag polar, best L/D, and the speeds for minimum drag and minimum "
        "power. Interference and excrescence allowances are included."
    ),
    "inputs": [
        {"key": "mass", "label": "Total Mass", "unit": "kg", "type": "number"},
        {"key": "wing_area", "label": "Wing Area (S)", "unit": "m^2", "type": "number"},
        {"key": "span", "label": "Wing Span (b)", "unit": "m", "type": "number"},
        {"key": "wing_mac", "label": "Wing MAC", "unit": "m", "type": "number"},
        {"key": "wing_tc", "label": "Wing Thickness Ratio", "type": "number",
         "default": "0.12"},
        {"key": "fuse_length", "label": "Fuselage Length", "unit": "m", "type": "number"},
        {"key": "fuse_diameter", "label": "Fuselage Width/Diameter", "unit": "m",
         "type": "number"},
        {"key": "tail_area", "label": "Total Tail Area", "unit": "m^2",
         "type": "number", "help": "Horizontal plus vertical, exposed planform."},
        {"key": "tail_mac", "label": "Tail Mean Chord", "unit": "m", "type": "number",
         "default": "0.12"},
        {"key": "velocity", "label": "Reference Speed", "unit": "m/s", "type": "number"},
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number",
         "default": "0"},
        {"key": "laminar", "label": "Laminar Run", "unit": "fraction",
         "type": "number", "default": "0.3",
         "help": "Small models hold laminar flow over much of the chord. "
                 "0.3-0.5 for a clean moulded wing, 0 for a rough built-up one."},
        {"key": "finish", "label": "Surface Finish", "type": "choice",
         "choices": ["Moulded composite", "Covered built-up", "Rough / exposed hardware"],
         "default": "Covered built-up"},
        {"key": "landing_gear", "label": "Landing Gear", "type": "choice",
         "choices": ["None / retracted", "Fixed, faired", "Fixed, exposed"],
         "default": "None / retracted"},
    ],
}

# Excrescence allowance as a fraction of the clean CD0: hinge gaps, control
# horns, antennae, screw heads and covering seams all add up on a model.
FINISH_PENALTY = {
    "Moulded composite": 0.06,
    "Covered built-up": 0.15,
    "Rough / exposed hardware": 0.28,
}

# Landing gear drag, referenced to wing area.
GEAR_CD = {
    "None / retracted": 0.0,
    "Fixed, faired": 0.008,
    "Fixed, exposed": 0.020,
}

INTERFERENCE = 1.08  # wing-fuselage and tail-fuselage junction penalty


def run(inputs):
    try:
        mass = units.positive(inputs, "mass", "kg", "Mass")
        wing_area = units.positive(inputs, "wing_area", "m^2", "Wing area")
        span = units.positive(inputs, "span", "m", "Span")
        wing_mac = units.positive(inputs, "wing_mac", "m", "Wing MAC")
        wing_tc = units.optional(inputs, "wing_tc", "", 0.12) or 0.12
        fuse_length = units.optional(inputs, "fuse_length", "m", 0.0)
        fuse_diameter = units.optional(inputs, "fuse_diameter", "m", 0.0)
        tail_area = units.optional(inputs, "tail_area", "m^2", 0.0)
        tail_mac = units.optional(inputs, "tail_mac", "m", 0.12) or 0.12
        velocity = units.positive(inputs, "velocity", "m/s", "Reference speed")
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        laminar = units.fraction(inputs, "laminar", 0.3)
        finish = inputs.get("finish") or "Covered built-up"
        gear = inputs.get("landing_gear") or "None / retracted"

        air = atmosphere.at(altitude)
        aspect_ratio = span ** 2 / wing_area
        weight = mass * G

        components = []

        def add(name, wetted, reference_length, form_factor):
            re = air.density * velocity * reference_length / air.viscosity
            cf = aero.skin_friction_coefficient(re, laminar)
            cd = cf * form_factor * wetted / wing_area
            components.append({"name": name, "wetted": wetted, "re": re,
                               "cf": cf, "ff": form_factor, "cd": cd})
            return cd

        # Wing: both surfaces, with a small bump for thickness.
        mach = velocity / air.sound_speed
        wing_wetted = wing_area * 2.0 * (1.0 + 0.25 * wing_tc)
        add("Wing", wing_wetted, wing_mac, aero.form_factor_wing(wing_tc, mach))

        if fuse_length > 0 and fuse_diameter > 0:
            fineness = fuse_length / fuse_diameter
            # Approximate the fuselage as a cylinder with rounded ends.
            fuse_wetted = math.pi * fuse_diameter * fuse_length * 0.85
            add("Fuselage", fuse_wetted, fuse_length,
                aero.form_factor_body(fineness))

        if tail_area > 0:
            add("Tail surfaces", tail_area * 2.04, tail_mac,
                aero.form_factor_wing(0.10, mach))

        cd0_clean = sum(c["cd"] for c in components)
        cd0_interference = cd0_clean * (INTERFERENCE - 1.0)
        cd0_excrescence = cd0_clean * FINISH_PENALTY.get(finish, 0.15)
        cd0_gear = GEAR_CD.get(gear, 0.0)
        cd0 = cd0_clean + cd0_interference + cd0_excrescence + cd0_gear

        oswald = aero.oswald_efficiency(aspect_ratio)
        k = aero.induced_drag_factor(aspect_ratio, oswald)
        best_ld, cl_best = aero.ld_max(cd0, k)

        r = report.Report("Drag Buildup")
        r.section("Conditions")
        r.value("Reference speed", velocity, "m/s", 2)
        r.value("Altitude", altitude, "m", 0)
        r.value("Air density", air.density, "kg/m^3", 4)
        r.value("Laminar run assumed", laminar * 100, "%", 0)
        r.value("Aspect ratio", aspect_ratio, "", 2)

        r.section("Component Buildup")
        rows = []
        for c in components:
            rows.append([c["name"], f"{c['wetted']:.4f}", f"{c['re']:,.0f}",
                         f"{c['cf']:.5f}", f"{c['ff']:.3f}", f"{c['cd']:.5f}",
                         f"{100 * c['cd'] / cd0:.1f}%"])
        rows.append(["Interference", "-", "-", "-", f"{INTERFERENCE:.2f}",
                     f"{cd0_interference:.5f}", f"{100 * cd0_interference / cd0:.1f}%"])
        rows.append([f"Finish ({finish.split()[0]})", "-", "-", "-", "-",
                     f"{cd0_excrescence:.5f}", f"{100 * cd0_excrescence / cd0:.1f}%"])
        if cd0_gear > 0:
            rows.append(["Landing gear", "-", "-", "-", "-", f"{cd0_gear:.5f}",
                         f"{100 * cd0_gear / cd0:.1f}%"])
        r.table(["Component", "Swet m^2", "Re", "Cf", "FF", "CD0", "Share"], rows)

        r.section("Drag Polar")
        r.value("CD0 (parasite)", cd0, "", 5)
        r.value("Oswald efficiency (e)", oswald, "", 3)
        r.value("Induced factor (k)", k, "", 5)
        r.text(f"  CD = {cd0:.5f} + {k:.5f} * CL^2")
        r.note(aero.oswald_note(aspect_ratio))

        r.section("Performance Points")
        v_min_drag = aero.speed_min_drag(mass, wing_area, cd0, k, altitude)
        v_min_power = aero.speed_min_power(mass, wing_area, cd0, k, altitude)
        r.value("Best L/D", best_ld, "", 2)
        r.value("  at CL", cl_best, "", 3)
        r.dual("Min drag speed (best glide)", v_min_drag, "m/s", "mph", 2)
        r.dual("Min power speed (best loiter)", v_min_power, "m/s", "mph", 2)
        r.value("Glide ratio at best L/D", best_ld, ":1", 2)
        r.value("Min sink rate", v_min_power / aero.ld_max(cd0, k)[0] * 1.155,
                "m/s", 2)
        r.value("Drag at reference speed",
                aero.dynamic_pressure(velocity, altitude) * wing_area
                * aero.drag_polar(aero.cl_required(mass, wing_area, velocity, altitude),
                                  cd0, k), "N", 3)

        r.section("Assessment")
        if cd0 < 0.025:
            r.bullet("Very clean for a model. Check the laminar assumption is "
                     "realistic for the actual surface finish.")
        elif cd0 < 0.045:
            r.bullet("Typical of a well-built sport model.")
        elif cd0 < 0.070:
            r.bullet("Draggy but normal for a built-up model with exposed gear "
                     "and hardware.")
        else:
            r.bullet("High. Look for exposed hardware, an oversized fuselage or "
                     "an unfaired undercarriage.")

        # Compare every contributor, not just the wetted-area components --
        # an unfaired undercarriage often dwarfs the airframe itself.
        contributors = [(c["name"], c["cd"]) for c in components]
        contributors.append(("Interference", cd0_interference))
        contributors.append(("Surface finish", cd0_excrescence))
        if cd0_gear > 0:
            contributors.append(("Landing gear", cd0_gear))
        biggest_name, biggest_cd = max(contributors, key=lambda item: item[1])
        r.bullet(f"{biggest_name} contributes the most parasite drag "
                 f"({100 * biggest_cd / cd0:.0f}%). Attack that first.")
        if cd0_gear > 0 and cd0_gear > 0.25 * cd0:
            r.bullet(f"Retracting or fairing the undercarriage would remove "
                     f"{100 * cd0_gear / cd0:.0f}% of the parasite drag and "
                     f"raise best L/D from {best_ld:.1f} to "
                     f"{aero.ld_max(cd0 - cd0_gear, k)[0]:.1f}.")
        if any(c["re"] < 100_000 for c in components):
            r.warn("Some components run below Re 100,000, where skin friction "
                   "correlations lose accuracy and aerofoil performance falls "
                   "off sharply.")

        figures = []
        if plotting.available():
            try:
                cls = [0.05 * i for i in range(1, 31)]
                cds = [aero.drag_polar(cl, cd0, k) for cl in cls]
                lds = [cl / cd for cl, cd in zip(cls, cds)]
                figures.append(plotting.line_chart(
                    "Drag Polar", "Drag coefficient CD", "Lift coefficient CL",
                    [("CD = CD0 + k CL^2", cds, cls)],
                    markers=[(f"L/D max = {best_ld:.1f}",
                              aero.drag_polar(cl_best, cd0, k), cl_best)]))
                figures.append(plotting.line_chart(
                    "Lift-to-Drag Ratio", "Lift coefficient CL", "L/D",
                    [("L/D", cls, lds)],
                    markers=[(f"Best {best_ld:.1f} at CL {cl_best:.2f}",
                              cl_best, best_ld)]))
                figures.append(plotting.bar_chart(
                    "Parasite Drag Breakdown", "CD0 contribution", "",
                    [c["name"] for c in components] + ["Interference", "Finish"]
                    + (["Gear"] if cd0_gear > 0 else []),
                    [c["cd"] for c in components] + [cd0_interference, cd0_excrescence]
                    + ([cd0_gear] if cd0_gear > 0 else [])))
            except Exception:
                r.note("Charts could not be generated.")

        return report.result(r, outputs={
            "CD0": {"value": cd0},
            "Induced Drag Factor (k)": {"value": k},
            "Best L/D": {"value": best_ld},
            "Best Glide Speed": {"value": v_min_drag, "unit": "m/s"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
