"""Explicit SI curve imports; no guessing units or skipping malformed rows."""
import csv
import math
from pathlib import Path


def read_curve_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        header = next(reader, None)
        if header != ["x", "y"]:
            raise ValueError("Curve CSV must start with x,y; values must use the documented SI units")
        points = []
        for number, row in enumerate(reader, 2):
            if len(row) != 2:
                raise ValueError(f"CSV line {number}: expected exactly two columns")
            try:
                x, y = map(float, row)
            except ValueError as exc:
                raise ValueError(f"CSV line {number}: nonnumeric value") from exc
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError(f"CSV line {number}: nonfinite value")
            if points and x <= points[-1][0]:
                raise ValueError(f"CSV line {number}: x must be strictly increasing")
            points.append([x, y])
        if len(points) < 2:
            raise ValueError("Curve needs at least two data rows")
    return points


def read_propeller_csv(path):
    """RPM,J,CT,CP rows grouped in strictly increasing RPM then J order."""
    slices = []
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        if next(reader, None) != ["rpm", "J", "CT", "CP"]:
            raise ValueError("Propeller CSV header must be rpm,J,CT,CP")
        for line, row in enumerate(reader, 2):
            if len(row) != 4:
                raise ValueError(f"CSV line {line}: expected four columns")
            rpm, j, ct, cp = map(float, row)
            if not all(math.isfinite(v) for v in (rpm, j, ct, cp)) or rpm <= 0 or j < 0:
                raise ValueError(f"CSV line {line}: invalid RPM/advance ratio or nonfinite coefficient")
            if not slices or slices[-1]["rpm"] != rpm:
                if slices and rpm <= slices[-1]["rpm"]:
                    raise ValueError("Propeller RPM slices must be strictly increasing")
                slices.append(dict(rpm=rpm, points=[]))
            points = slices[-1]["points"]
            if points and j <= points[-1][0]:
                raise ValueError("Advance ratio must increase within each RPM slice")
            points.append([j, ct, cp])
    if len(slices) < 2 or any(len(row["points"]) < 2 for row in slices):
        raise ValueError("Propeller map needs two RPM slices with at least two advance ratios each")
    return slices
