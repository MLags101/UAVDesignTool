"""
Aerofoil Coordinate Converter

Reads aerofoil coordinates and writes CAD-ready curve files. Extended from the
earlier version, which only understood the Airfoil Tools CSV export and only
wrote a SolidWorks point file:

* Reads Selig and Lednicer ``.dat`` files -- the UIUC database format that most
  aerofoil coordinates actually come in -- as well as the Airfoil Tools CSV,
  detecting the format automatically.
* Writes SolidWorks curve files, DXF polylines and plain CSV.
* Can add a finite trailing-edge thickness, since a knife-edge trailing edge is
  unbuildable and will not loft cleanly in CAD.
* Generates a matched root and tip pair for a tapered wing in one pass.

The input path is taken as given, rather than being guessed from the tool
script's own location.
"""

import math
import os

from uavlib import report, units

TOOL_METADATA = {
    "name": "Aerofoil Coordinate Converter",
    "category": "Fixed Wing / Geometry",
    "description": (
        "Converts Selig/Lednicer .dat or Airfoil Tools CSV coordinates into "
        "SolidWorks curve, DXF or CSV files, scaled to chord. Optionally adds "
        "trailing-edge thickness and generates a root/tip pair for a tapered "
        "wing."
    ),
    "inputs": [
        {"key": "input_file", "label": "Coordinate File", "type": "file",
         "help": "A .dat (Selig or Lednicer) or .csv file."},
        {"key": "output_format", "label": "Output Format", "type": "choice",
         "choices": ["SolidWorks curve (.txt)", "DXF polyline (.dxf)",
                     "CSV (.csv)"],
         "default": "SolidWorks curve (.txt)"},
        {"key": "root_chord", "label": "Root Chord", "unit": "m",
         "type": "number", "help": "Accepts mm or inches."},
        {"key": "tip_chord", "label": "Tip Chord", "unit": "m", "type": "number",
         "help": "Optional. Also writes a scaled tip section."},
        {"key": "te_thickness", "label": "Trailing Edge Thickness", "unit": "m",
         "type": "number", "default": "0",
         "help": "Opens a knife-edge trailing edge. 0.5-1.5 mm is typical for "
                 "a model."},
        {"key": "output_dir", "label": "Output Folder", "type": "file",
         "help": "Blank writes alongside the input file."},
        {"key": "output_name", "label": "Output Base Name", "type": "text",
         "help": "Blank uses the aerofoil name from the file."},
    ],
}


def _read_numbers(line):
    """Return the first two numbers on a line, or None."""
    cleaned = line.replace(",", " ").strip()
    if not cleaned:
        return None
    parts = cleaned.split()
    if len(parts) < 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def parse_coordinates(path):
    """Read an aerofoil file, returning (name, points, format description).

    Handles the three formats that matter:

    * Selig -- a single loop from the trailing edge over the top, round the
      leading edge and back along the bottom.
    * Lednicer -- a header pair giving surface point counts, then the upper
      surface from the leading edge, then the lower surface.
    * Airfoil Tools CSV -- a labelled block after an 'Airfoil surface' header.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()

    name = os.path.splitext(os.path.basename(path))[0]

    # Airfoil Tools CSV: coordinates sit under an "Airfoil surface" heading.
    for index, line in enumerate(lines):
        if "airfoil surface" in line.lower():
            points = []
            for following in lines[index + 1:]:
                stripped = following.strip()
                if not stripped or stripped == ",":
                    break
                if any(marker in stripped.lower()
                       for marker in ("camber line", "chord line")):
                    break
                pair = _read_numbers(following)
                if pair:
                    points.append(pair)
            if points:
                return name, points, "Airfoil Tools CSV"

    # Otherwise a .dat file: the first line is usually the aerofoil name.
    header = lines[0].strip() if lines else ""
    if header and _read_numbers(header) is None:
        name = header
        body = lines[1:]
    else:
        body = lines

    numeric = []
    for line in body:
        pair = _read_numbers(line)
        if pair:
            numeric.append(pair)

    if not numeric:
        raise ValueError("no coordinate pairs found in the file.")

    # Lednicer files start with the two surface point counts, which are values
    # well above 1.0 -- ordinary coordinates never are.
    first_x, first_y = numeric[0]
    if first_x > 1.5 and first_y > 1.5:
        upper_count = int(round(first_x))
        lower_count = int(round(first_y))
        rest = numeric[1:]
        if len(rest) < upper_count + lower_count:
            raise ValueError("Lednicer header does not match the point count.")
        upper = rest[:upper_count]
        lower = rest[upper_count:upper_count + lower_count]
        # Convert to a single Selig-style loop: upper reversed, then lower.
        points = list(reversed(upper)) + lower[1:]
        return name, points, "Lednicer .dat"

    return name, numeric, "Selig .dat"


def apply_trailing_edge(points, thickness_ratio):
    """Open the trailing edge by ``thickness_ratio`` of chord.

    The opening is tapered in from the leading edge so the section shape is
    preserved forward; only the aft portion is displaced.
    """
    if thickness_ratio <= 0:
        return points
    half = thickness_ratio / 2.0
    adjusted = []
    for x, y in points:
        # Displacement grows with x so the leading edge is untouched.
        offset = half * max(0.0, min(x, 1.0))
        adjusted.append((x, y + offset if y >= 0 else y - offset))
    return adjusted


def normalise(points):
    """Scale and shift so the chord runs from x = 0 to x = 1."""
    xs = [p[0] for p in points]
    x_min, x_max = min(xs), max(xs)
    chord = x_max - x_min
    if chord <= 0:
        raise ValueError("coordinates have zero chord length.")
    return [((x - x_min) / chord, y / chord) for x, y in points]


def write_solidworks(path, points, chord):
    with open(path, "w", encoding="utf-8") as handle:
        for x, y in points:
            handle.write(f"{x * chord:.6f}\t{y * chord:.6f}\t0.000000\n")


def write_csv(path, points, chord):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("X,Y,Z\n")
        for x, y in points:
            handle.write(f"{x * chord:.6f},{y * chord:.6f},0.000000\n")


def write_dxf(path, points, chord):
    """Minimal DXF with a single closed LWPOLYLINE, which every CAD tool reads."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("0\nSECTION\n2\nENTITIES\n")
        handle.write("0\nLWPOLYLINE\n8\nAIRFOIL\n")
        handle.write(f"90\n{len(points)}\n70\n1\n")
        for x, y in points:
            handle.write(f"10\n{x * chord:.6f}\n20\n{y * chord:.6f}\n")
        handle.write("0\nENDSEC\n0\nEOF\n")


WRITERS = {
    "SolidWorks curve (.txt)": (write_solidworks, ".txt"),
    "DXF polyline (.dxf)": (write_dxf, ".dxf"),
    "CSV (.csv)": (write_csv, ".csv"),
}


def split_surfaces(points):
    """Split a Selig-style loop into upper and lower surfaces.

    The loop runs trailing edge -> upper -> leading edge -> lower -> trailing
    edge, so the leading edge is simply the minimum-x point. Both surfaces are
    returned with x increasing.
    """
    le_index = min(range(len(points)), key=lambda i: points[i][0])
    upper = sorted(points[:le_index + 1], key=lambda p: p[0])
    lower = sorted(points[le_index:], key=lambda p: p[0])
    return upper, lower


def _interpolate(surface, x):
    """Linear interpolation of a surface at a chord station."""
    if not surface:
        return None
    if x <= surface[0][0]:
        return surface[0][1]
    if x >= surface[-1][0]:
        return surface[-1][1]
    for i in range(1, len(surface)):
        x0, y0 = surface[i - 1]
        x1, y1 = surface[i]
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return surface[-1][1]


def section_properties(points):
    """Maximum thickness and camber, and where along the chord they occur.

    The upper and lower surfaces rarely share x stations -- a cambered section's
    coordinates are offset perpendicular to the camber line -- so the lower
    surface is interpolated onto the upper surface's stations rather than
    matched by equality.
    """
    upper, lower = split_surfaces(points)
    if len(upper) < 2 or len(lower) < 2:
        return 0.0, 0.0, 0.0, 0.0

    thickness, thickness_at = 0.0, 0.0
    camber, camber_at = 0.0, 0.0

    stations = sorted({p[0] for p in upper} | {p[0] for p in lower})
    for x in stations:
        if not 0.0 <= x <= 1.0:
            continue
        top = _interpolate(upper, x)
        bottom = _interpolate(lower, x)
        if top is None or bottom is None:
            continue
        local_thickness = abs(top - bottom)
        local_camber = (top + bottom) / 2.0
        if local_thickness > thickness:
            thickness, thickness_at = local_thickness, x
        if abs(local_camber) > abs(camber):
            camber, camber_at = local_camber, x
    return thickness, thickness_at, camber, camber_at


def run(inputs):
    try:
        input_file = (inputs.get("input_file") or "").strip()
        if not input_file:
            return report.error("select a coordinate file (.dat or .csv).")
        if not os.path.exists(input_file):
            return report.error(f"file not found: {input_file}")

        output_format = inputs.get("output_format") or "SolidWorks curve (.txt)"
        root_chord = units.positive(inputs, "root_chord", "m", "Root chord")
        tip_chord = units.optional(inputs, "tip_chord", "m", 0.0)
        te_thickness = units.optional(inputs, "te_thickness", "m", 0.0)
        output_dir = (inputs.get("output_dir") or "").strip()
        base_name = (inputs.get("output_name") or "").strip()

        name, raw_points, detected = parse_coordinates(input_file)
        points = normalise(raw_points)

        if te_thickness > 0:
            points = apply_trailing_edge(points, te_thickness / root_chord)

        thickness, thickness_at, camber, camber_at = section_properties(points)

        if not output_dir:
            output_dir = os.path.dirname(os.path.abspath(input_file))
        elif os.path.isfile(output_dir):
            output_dir = os.path.dirname(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        safe_name = "".join(c for c in (base_name or name)
                            if c.isalnum() or c in "-_ ").strip() or "airfoil"
        writer, extension = WRITERS[output_format]

        written = []
        root_path = os.path.join(output_dir,
                                 f"{safe_name}_root_{root_chord * 1000:.0f}mm{extension}")
        writer(root_path, points, root_chord)
        written.append(("Root", root_chord, root_path))

        if tip_chord > 0:
            tip_points = points
            if te_thickness > 0:
                # Keep the trailing edge the same absolute thickness at the tip.
                tip_points = apply_trailing_edge(
                    normalise(raw_points), te_thickness / tip_chord)
            tip_path = os.path.join(
                output_dir, f"{safe_name}_tip_{tip_chord * 1000:.0f}mm{extension}")
            writer(tip_path, tip_points, tip_chord)
            written.append(("Tip", tip_chord, tip_path))

        r = report.Report("Aerofoil Conversion")
        r.section("Source")
        r.value("File", os.path.basename(input_file))
        r.value("Detected format", detected)
        r.value("Aerofoil name", name)
        r.value("Points read", len(raw_points), "", 0)

        r.section("Section Properties")
        r.value("Max thickness", thickness * 100, "% chord", 2)
        r.value("  at", thickness_at * 100, "% chord", 1)
        r.value("Max camber", camber * 100, "% chord", 2)
        r.value("  at", camber_at * 100, "% chord", 1)
        if abs(camber) < 0.005:
            r.bullet("Symmetric section: no camber. Suits aerobatic models and "
                     "tail surfaces.")
        elif camber > 0.04:
            r.bullet("Highly cambered: good CLmax and low-speed lift, at the "
                     "cost of a nose-down pitching moment needing more tail.")

        r.section("Output")
        r.value("Format", output_format)
        r.value("Folder", output_dir)
        if te_thickness > 0:
            r.value("Trailing edge opened to", te_thickness * 1000, "mm", 2)
            r.value("  as % of root chord", 100 * te_thickness / root_chord, "%", 2)
        rows = []
        for label, chord, path in written:
            rows.append([label, f"{chord * 1000:.1f}",
                         f"{chord * thickness * 1000:.2f}",
                         os.path.basename(path)])
        r.table(["Section", "Chord mm", "Thick mm", "File"], rows)

        r.section("Next Steps")
        if output_format.startswith("SolidWorks"):
            r.bullet("Insert > Curve > Curve Through XYZ Points, then select "
                     "the .txt file.")
            r.bullet("The file is tab-delimited X/Y/Z in metres. If your part "
                     "is in millimetres, scale by 1000 on import.")
        elif output_format.startswith("DXF"):
            r.bullet("Insert the .dxf as a sketch entity; it contains one "
                     "closed polyline on layer AIRFOIL.")
        else:
            r.bullet("The CSV has an X,Y,Z header and can be imported by most "
                     "CAD and analysis tools.")
        if tip_chord > 0:
            r.bullet("Loft between the root and tip sections, remembering to "
                     "apply sweep, dihedral and any washout as you position "
                     "the tip rib.")
        if te_thickness <= 0:
            r.bullet("A knife-edge trailing edge often fails to loft and cannot "
                     "be built. Consider opening it by 0.5-1.5 mm.")

        return report.result(r, outputs={
            "Aerofoil": {"value": name},
            "Thickness Ratio": {"value": thickness},
            "Max Camber": {"value": camber},
        })

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except OSError as exc:
        return report.error(f"file error: {exc}")
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
