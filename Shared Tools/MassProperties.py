"""
Mass Properties and Weight-and-Balance

Takes a component list and returns all-up mass, centre of gravity and moments
of inertia. Pair it with the CG & Static Margin tool: this one tells you where
the CG *is*, that one tells you where it *should be*.

Components are entered one per line as:

    name, mass, x [, y, z]

Mass accepts units (``120 g``, ``0.3 kg``, ``4 oz``) and positions accept them
too (``250 mm``, ``9.8 in``). X is positive aft, Y positive to the right, Z
positive up, all measured from whatever datum you choose -- normally the wing
root leading edge for an aeroplane, or the frame centre for a multirotor.
"""

from uavlib import report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Mass Properties & CG",
    "category": "Shared / Layout",
    "description": (
        "All-up mass, centre of gravity and inertia from a component list. "
        "Enter one component per line as 'name, mass, x' with optional y and z. "
        "Also solves for where to place a chosen component to hit a target CG."
    ),
    "inputs": [
        {"key": "components", "label": "Components", "type": "text",
         "help": "One per line: name, mass, x [, y, z]. Example: "
                 "Battery, 420 g, 120 mm"},
        {"key": "target_cg", "label": "Target CG (x)", "unit": "m",
         "type": "number",
         "help": "Optional. Reports the ballast or shift needed to reach it."},
        {"key": "movable", "label": "Movable Component", "type": "text",
         "help": "Optional. Name of the component to relocate to hit the "
                 "target CG, usually the battery."},
        {"key": "mac", "label": "MAC Length", "unit": "m", "type": "number",
         "help": "Optional. Expresses the CG as a percentage of MAC."},
        {"key": "mac_le", "label": "MAC Leading Edge (x)", "unit": "m",
         "type": "number", "default": "0"},
    ],
}

EXAMPLE = """Motor, 60 g, 20 mm
Battery, 420 g, 120 mm
Receiver, 12 g, 250 mm
Wing, 380 g, 190 mm
Fuselage, 300 g, 300 mm
Tail, 90 g, 800 mm
Servos, 40 g, 700 mm"""


def parse_components(text):
    """Parse the component table, returning rows and any per-line errors."""
    rows, errors = [], []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            errors.append(f"Line {number}: need at least 'name, mass, x'.")
            continue
        name = parts[0]
        try:
            mass = units.parse(parts[1], "kg", None)
            x = units.parse(parts[2], "m", None)
            y = units.parse(parts[3], "m", 0.0) if len(parts) > 3 else 0.0
            z = units.parse(parts[4], "m", 0.0) if len(parts) > 4 else 0.0
        except units.UnitError as exc:
            errors.append(f"Line {number}: {exc}")
            continue
        if mass is None or x is None:
            errors.append(f"Line {number}: mass and x are required.")
            continue
        if mass <= 0:
            errors.append(f"Line {number}: mass must be greater than zero.")
            continue
        rows.append({"name": name, "mass": mass, "x": x,
                     "y": y or 0.0, "z": z or 0.0})
    return rows, errors


def run(inputs):
    try:
        text = (inputs.get("components") or "").strip()
        if not text:
            r = report.Report("Mass Properties")
            r.text("  Enter one component per line as:")
            r.text("")
            r.text("      name, mass, x [, y, z]")
            r.text("")
            r.text("  Units are accepted on every value, so both of these work:")
            r.text("      Battery, 420 g, 120 mm")
            r.text("      Battery, 0.42, 0.12")
            r.blank()
            r.section("Example")
            for line in EXAMPLE.splitlines():
                r.text(f"      {line}")
            r.blank()
            r.text("  X is positive aft, Y to the right, Z up, from any datum")
            r.text("  you choose. The wing root leading edge is the usual one.")
            return str(r)

        rows, errors = parse_components(text)
        if errors and not rows:
            return report.error("could not read any component.\n  "
                                + "\n  ".join(errors))
        if not rows:
            return report.error("no components found.")

        total_mass = sum(c["mass"] for c in rows)
        cg_x = sum(c["mass"] * c["x"] for c in rows) / total_mass
        cg_y = sum(c["mass"] * c["y"] for c in rows) / total_mass
        cg_z = sum(c["mass"] * c["z"] for c in rows) / total_mass

        # Moments of inertia about the CG, treating each item as a point mass.
        ixx = sum(c["mass"] * ((c["y"] - cg_y) ** 2 + (c["z"] - cg_z) ** 2)
                  for c in rows)
        iyy = sum(c["mass"] * ((c["x"] - cg_x) ** 2 + (c["z"] - cg_z) ** 2)
                  for c in rows)
        izz = sum(c["mass"] * ((c["x"] - cg_x) ** 2 + (c["y"] - cg_y) ** 2)
                  for c in rows)

        target = units.optional(inputs, "target_cg", "m", 0.0)
        movable = (inputs.get("movable") or "").strip()
        mac = units.optional(inputs, "mac", "m", 0.0)
        mac_le = units.optional(inputs, "mac_le", "m", 0.0)

        r = report.Report("Mass Properties")

        if errors:
            r.section("Skipped Lines")
            for message in errors:
                r.warn(message)

        r.section("Components")
        table_rows = []
        for c in sorted(rows, key=lambda c: -c["mass"]):
            table_rows.append([
                c["name"][:22],
                f"{c['mass'] * 1000:.0f}",
                f"{100 * c['mass'] / total_mass:.1f}%",
                f"{c['x'] * 1000:.0f}",
                f"{c['mass'] * c['x'] * 1000:.1f}",
            ])
        r.table(["Component", "Mass g", "Share", "x mm", "Moment g.m"], table_rows)

        r.section("Totals")
        r.dual("All-up mass", total_mass, "kg", "lb", 4)
        r.value("  in grams", total_mass * 1000, "g", 0)
        r.dual("Weight", total_mass * G, "N", "lbf", 3)
        r.value("Components", len(rows), "", 0)

        r.section("Centre of Gravity")
        r.dual("CG x (aft of datum)", cg_x, "m", "in", 4)
        r.value("  in mm", cg_x * 1000, "mm", 1)
        if any(abs(c["y"]) > 1e-9 for c in rows):
            r.dual("CG y (lateral)", cg_y, "m", "in", 4)
            if abs(cg_y) > 0.005:
                r.warn(f"Lateral CG is {cg_y * 1000:.1f} mm off centre. This "
                       "will need trim and, on a multirotor, costs authority.")
        if any(abs(c["z"]) > 1e-9 for c in rows):
            r.dual("CG z (vertical)", cg_z, "m", "in", 4)

        if mac > 0:
            percent = 100.0 * (cg_x - mac_le) / mac
            r.value("CG as % of MAC", percent, "%", 1)
            if percent < 15:
                r.bullet("Well forward. Very stable but heavy on the elevator.")
            elif percent <= 35:
                r.bullet("In the usual band for a stable model (15-35% MAC).")
            else:
                r.warn("Aft of 35% MAC. Check the static margin before flying.")

        r.section("Moments of Inertia (point-mass estimate)")
        r.value("Ixx (roll)", ixx, "kg.m^2", 6)
        r.value("Iyy (pitch)", iyy, "kg.m^2", 6)
        r.value("Izz (yaw)", izz, "kg.m^2", 6)
        r.text("  Point-mass estimates ignore each item's own inertia, so they")
        r.text("  run low -- typically by 5-15% for compact components.")

        if target > 0:
            r.section("Reaching the Target CG")
            shift = target - cg_x
            r.dual("Target CG", target, "m", "in", 4)
            r.value("CG error", shift * 1000, "mm", 1,
                    note="positive means the CG must move aft")

            if abs(shift) < 1e-4:
                r.bullet("Already on target.")
            else:
                item = next((c for c in rows
                             if c["name"].lower() == movable.lower()), None)
                if item:
                    # Moving a mass m by d shifts the CG by m*d/total.
                    move = shift * total_mass / item["mass"]
                    r.blank()
                    r.value(f"Move '{item['name']}'", move * 1000, "mm", 1,
                            note="aft" if move > 0 else "forward")
                    r.value("  from", item["x"] * 1000, "mm", 1)
                    r.value("  to", (item["x"] + move) * 1000, "mm", 1)
                elif movable:
                    r.warn(f"No component named '{movable}'. Names must match "
                           "exactly.")

                # Ballast is the fallback when nothing can be moved.
                r.blank()
                r.text("  Ballast alternative (added at the extremes):")
                for label, position in (("nose", min(c["x"] for c in rows)),
                                        ("tail", max(c["x"] for c in rows))):
                    lever = position - target
                    if abs(lever) > 1e-6:
                        ballast = total_mass * (cg_x - target) / lever
                        if ballast > 0:
                            r.value(f"  at the {label} ({position * 1000:.0f} mm)",
                                    ballast * 1000, "g", 1)

        r.section("Notes")
        heaviest = max(rows, key=lambda c: c["mass"])
        r.bullet(f"'{heaviest['name']}' is {100 * heaviest['mass'] / total_mass:.0f}% "
                 "of all-up mass; moving it is the most effective CG adjustment.")
        r.bullet("Weigh components rather than estimating them. A 10% error on "
                 "the battery moves the CG more than most trim changes.")

        return report.result(r, outputs={
            "All-Up Mass": {"value": total_mass, "unit": "kg"},
            "CG Position": {"value": cg_x, "unit": "m"},
            "Roll Inertia (Ixx)": {"value": ixx, "unit": "kg.m^2"},
            "Pitch Inertia (Iyy)": {"value": iyy, "unit": "kg.m^2"},
            "Yaw Inertia (Izz)": {"value": izz, "unit": "kg.m^2"},
        })

    except units.UnitError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
