"""
Aerofoil Polar Reader

Reads an XFOIL or Airfoil Tools polar and pulls out the numbers that decide
whether a section suits the model: maximum Cl/Cd and the angle it occurs at,
Clmax and the stall angle, and the drag at the actual operating Cl.

Polars are Reynolds-specific. A section that looks excellent at Re 500,000 can
be mediocre at the Re 90,000 a small model actually flies at, which is the most
common aerofoil selection mistake.
"""

import math
import os

from uavlib import atmosphere, plotting, report, units

TOOL_METADATA = {
    "name": "Aerofoil Polar Reader",
    "category": "Fixed Wing / Aerodynamics",
    "description": (
        "Reads an XFOIL or Airfoil Tools polar file and reports best L/D, "
        "Clmax, stall angle, minimum drag and the performance at your actual "
        "operating lift coefficient."
    ),
    "inputs": [
        {"key": "polar_file", "label": "Polar File", "type": "file",
         "help": "XFOIL .txt/.pol output, or an Airfoil Tools CSV polar."},
        {"key": "operating_cl", "label": "Operating CL", "type": "number",
         "help": "Optional: your cruise lift coefficient."},
        {"key": "mass", "label": "Total Mass", "unit": "kg", "type": "number",
         "help": "Optional: with wing area and speed, derives the operating CL."},
        {"key": "wing_area", "label": "Wing Area", "unit": "m^2",
         "type": "number"},
        {"key": "velocity", "label": "Cruise Speed", "unit": "m/s",
         "type": "number"},
        {"key": "chord", "label": "Reference Chord", "unit": "m",
         "type": "number", "help": "Optional: checks the polar's Reynolds "
                                   "number against your actual one."},
    ],
}


def parse_polar(path):
    """Read a polar file into rows of alpha, Cl, Cd, Cm.

    XFOIL writes a fixed-column table under a dashed rule, preceded by a header
    naming the Reynolds and Mach numbers. Airfoil Tools exports the same data as
    a comma-separated table. Both are handled by finding the numeric block.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()

    reynolds, mach, name = None, None, os.path.splitext(os.path.basename(path))[0]

    for line in lines[:40]:
        lowered = line.lower()
        if "re =" in lowered or "reynolds" in lowered:
            cleaned = lowered.replace("re =", " ").replace("reynolds", " ")
            cleaned = cleaned.replace("number", " ").replace("=", " ")
            for token in cleaned.replace(",", "").split():
                try:
                    value = float(token.replace("e", "E"))
                    if value > 1000:
                        reynolds = value
                        break
                except ValueError:
                    continue
        if "mach" in lowered and mach is None:
            for token in lowered.replace("mach", " ").replace("=", " ").split():
                try:
                    mach = float(token)
                    break
                except ValueError:
                    continue

    rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.replace(",", " ").split()
        if len(parts) < 3:
            continue
        try:
            values = [float(p) for p in parts[:4]]
        except ValueError:
            continue
        alpha, cl, cd = values[0], values[1], values[2]
        cm = values[3] if len(values) > 3 else 0.0
        # Filter out header rows that happen to parse, and impossible drag.
        if not (-40 <= alpha <= 40) or cd <= 0 or cd > 1.0 or abs(cl) > 4:
            continue
        rows.append({"alpha": alpha, "cl": cl, "cd": cd, "cm": cm})

    if not rows:
        raise ValueError("no polar data found. Expected columns of "
                         "alpha, Cl, Cd [, Cm].")

    rows.sort(key=lambda row: row["alpha"])
    return name, reynolds, mach, rows


def run(inputs):
    try:
        path = (inputs.get("polar_file") or "").strip()
        if not path:
            return report.error("select an XFOIL or Airfoil Tools polar file.")
        if not os.path.exists(path):
            return report.error(f"file not found: {path}")

        name, reynolds, mach, rows = parse_polar(path)

        operating_cl = units.optional(inputs, "operating_cl", "", 0.0)
        mass = units.optional(inputs, "mass", "kg", 0.0)
        wing_area = units.optional(inputs, "wing_area", "m^2", 0.0)
        velocity = units.optional(inputs, "velocity", "m/s", 0.0)
        chord = units.optional(inputs, "chord", "m", 0.0)

        if operating_cl <= 0 and mass > 0 and wing_area > 0 and velocity > 0:
            from uavlib import aero
            operating_cl = aero.cl_required(mass, wing_area, velocity)

        for row in rows:
            row["ld"] = row["cl"] / row["cd"]

        best = max(rows, key=lambda row: row["ld"])
        cl_max_row = max(rows, key=lambda row: row["cl"])
        min_drag = min(rows, key=lambda row: row["cd"])

        # Zero-lift angle, by interpolation across the Cl = 0 crossing.
        alpha_zero_lift = None
        for i in range(1, len(rows)):
            if rows[i - 1]["cl"] <= 0 <= rows[i]["cl"]:
                span_cl = rows[i]["cl"] - rows[i - 1]["cl"]
                if abs(span_cl) > 1e-9:
                    fraction = -rows[i - 1]["cl"] / span_cl
                    alpha_zero_lift = (rows[i - 1]["alpha"]
                                       + fraction * (rows[i]["alpha"]
                                                     - rows[i - 1]["alpha"]))
                break

        # Lift-curve slope over the linear region.
        linear = [row for row in rows if -4 <= row["alpha"] <= 6]
        slope = None
        if len(linear) >= 2:
            slope = ((linear[-1]["cl"] - linear[0]["cl"])
                     / (linear[-1]["alpha"] - linear[0]["alpha"]))

        r = report.Report("Aerofoil Polar")
        r.section("Source")
        r.value("File", os.path.basename(path))
        r.value("Aerofoil", name)
        r.value("Data points", len(rows), "", 0)
        r.value("Alpha range",
                f"{rows[0]['alpha']:.1f} to {rows[-1]['alpha']:.1f}", "deg")
        if reynolds:
            r.value("Polar Reynolds number", reynolds, "", 0)
        if mach is not None:
            r.value("Mach", mach, "", 3)

        r.section("Key Points")
        r.value("Best L/D", best["ld"], "", 1)
        r.value("  at alpha", best["alpha"], "deg", 2)
        r.value("  at Cl", best["cl"], "", 3)
        r.value("  at Cd", best["cd"], "", 5)
        r.blank()
        r.value("Clmax", cl_max_row["cl"], "", 3)
        r.value("  at alpha (stall)", cl_max_row["alpha"], "deg", 2)
        r.value("  Cd there", cl_max_row["cd"], "", 5)
        r.blank()
        r.value("Minimum Cd", min_drag["cd"], "", 5)
        r.value("  at alpha", min_drag["alpha"], "deg", 2)
        r.value("  at Cl", min_drag["cl"], "", 3)
        if alpha_zero_lift is not None:
            r.value("Zero-lift angle", alpha_zero_lift, "deg", 2)
        if slope:
            r.value("Lift-curve slope", slope, "per deg", 4)
            r.value("  per radian", slope * 180 / math.pi, "", 3)
            r.value("  vs thin-aerofoil 2*pi", slope * 180 / math.pi / (2 * math.pi),
                    "of theory", 3)

        if operating_cl > 0:
            # Interpolate the polar at the operating lift coefficient.
            ascending = [row for row in rows if row["alpha"] <= cl_max_row["alpha"]]
            match = None
            for i in range(1, len(ascending)):
                low, high = ascending[i - 1], ascending[i]
                if min(low["cl"], high["cl"]) <= operating_cl <= max(low["cl"],
                                                                    high["cl"]):
                    span_cl = high["cl"] - low["cl"]
                    fraction = ((operating_cl - low["cl"]) / span_cl
                                if abs(span_cl) > 1e-9 else 0.0)
                    match = {
                        "alpha": low["alpha"] + fraction * (high["alpha"] - low["alpha"]),
                        "cd": low["cd"] + fraction * (high["cd"] - low["cd"]),
                        "cm": low["cm"] + fraction * (high["cm"] - low["cm"]),
                    }
                    break

            r.section("At Your Operating Point")
            r.value("Operating Cl", operating_cl, "", 3)
            if match:
                r.value("Angle of attack", match["alpha"], "deg", 2)
                r.value("Cd", match["cd"], "", 5)
                r.value("L/D", operating_cl / match["cd"], "", 1)
                r.value("Cm", match["cm"], "", 4)
                r.value("Margin to Clmax",
                        100 * (1 - operating_cl / cl_max_row["cl"]), "%", 1)
                r.value("Efficiency vs best L/D",
                        100 * (operating_cl / match["cd"]) / best["ld"], "%", 1)
                if operating_cl / match["cd"] < best["ld"] * 0.85:
                    r.bullet(f"Operating well off the section's best point. "
                             f"Cl {best['cl']:.2f} would give L/D "
                             f"{best['ld']:.1f} against "
                             f"{operating_cl / match['cd']:.1f} here.")
                if operating_cl > cl_max_row["cl"] * 0.85:
                    r.warn("Operating within 15% of Clmax leaves little margin "
                           "for gusts or manoeuvre.")
            else:
                r.warn(f"Cl {operating_cl:.3f} lies outside this polar's range "
                       f"(max {cl_max_row['cl']:.3f}). The section cannot "
                       "deliver that lift coefficient at this Reynolds number.")

        if chord > 0 and velocity > 0:
            actual_re = atmosphere.reynolds(velocity, chord)
            r.section("Reynolds Check")
            r.value("Your Reynolds number", actual_re, "", 0)
            if reynolds:
                r.value("Polar Reynolds number", reynolds, "", 0)
                ratio = actual_re / reynolds
                r.value("Ratio", ratio, "", 2)
                if ratio < 0.6 or ratio > 1.7:
                    r.warn(f"Your Reynolds number differs from the polar's by "
                           f"{abs(1 - ratio) * 100:.0f}%. Drag and Clmax will "
                           "not match this data -- find a polar nearer "
                           f"Re {actual_re:,.0f}.")
                else:
                    r.bullet("The polar is close enough to your operating "
                             "Reynolds number to be trusted.")
            r.blank()
            r.text(f"  {atmosphere.reynolds_note(actual_re)}")

        r.section("Selected Data")
        step = max(1, len(rows) // 14)
        table_rows = []
        for row in rows[::step]:
            marker = ""
            if row is best:
                marker = "<-- best L/D"
            elif row is cl_max_row:
                marker = "<-- Clmax"
            table_rows.append([f"{row['alpha']:.1f}", f"{row['cl']:.3f}",
                               f"{row['cd']:.5f}", f"{row['ld']:.1f}",
                               f"{row['cm']:.4f}", marker])
        r.table(["Alpha", "Cl", "Cd", "L/D", "Cm", ""], table_rows)

        figures = []
        if plotting.available():
            try:
                alphas = [row["alpha"] for row in rows]
                cls = [row["cl"] for row in rows]
                cds = [row["cd"] for row in rows]
                lds = [row["ld"] for row in rows]
                figures.append(plotting.line_chart(
                    f"{name}: Lift Curve", "Angle of attack (deg)",
                    "Lift coefficient Cl", [("Cl", alphas, cls)],
                    markers=[(f"Clmax {cl_max_row['cl']:.2f}",
                              cl_max_row["alpha"], cl_max_row["cl"])]))
                figures.append(plotting.line_chart(
                    f"{name}: Drag Polar", "Drag coefficient Cd",
                    "Lift coefficient Cl", [("Polar", cds, cls)],
                    markers=[(f"Best L/D {best['ld']:.1f}", best["cd"],
                              best["cl"])]))
                figures.append(plotting.line_chart(
                    f"{name}: L/D vs Alpha", "Angle of attack (deg)", "L/D",
                    [("L/D", alphas, lds)],
                    markers=[(f"Best {best['ld']:.1f} at "
                              f"{best['alpha']:.1f} deg", best["alpha"],
                              best["ld"])]))
            except Exception:
                r.note("Charts could not be generated.")

        return report.result(r, outputs={
            "Aerofoil Clmax": {"value": cl_max_row["cl"]},
            "Stall Angle": {"value": cl_max_row["alpha"], "unit": "deg"},
            "Best Section L/D": {"value": best["ld"]},
            "Minimum Cd": {"value": min_drag["cd"]},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except OSError as exc:
        return report.error(f"file error: {exc}")
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
