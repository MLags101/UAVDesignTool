"""Unit parsing and formatting.

Tool inputs arrive as free text. ``parse`` accepts a bare number, which keeps
its SI meaning, or a number with a unit suffix::

    parse("10 in", "m")     -> 0.254
    parse("0.254", "m")     -> 0.254
    parse("3.3 lb", "kg")   -> 1.4969
    parse("10x4.7", "m")    -> 0.254   (prop size, diameter taken)

This keeps every existing project working while letting RC spec sheets be typed
in as printed.
"""

import math
import re

# Multiplicative factor to the SI base unit for each recognised suffix, grouped
# by the physical dimension the suffix belongs to.
_FACTORS = {
    "length": {
        "m": 1.0, "meter": 1.0, "metre": 1.0, "meters": 1.0, "metres": 1.0,
        "cm": 0.01, "mm": 0.001, "km": 1000.0,
        "in": 0.0254, "inch": 0.0254, "inches": 0.0254, '"': 0.0254,
        "ft": 0.3048, "foot": 0.3048, "feet": 0.3048, "'": 0.3048,
    },
    "mass": {
        "kg": 1.0, "kgs": 1.0, "kilogram": 1.0, "kilograms": 1.0,
        "g": 0.001, "gram": 0.001, "grams": 0.001,
        "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237,
        "pounds": 0.45359237,
        "oz": 0.028349523, "ounce": 0.028349523, "ounces": 0.028349523,
    },
    "speed": {
        "m/s": 1.0, "mps": 1.0, "ms": 1.0,
        "km/h": 1 / 3.6, "kph": 1 / 3.6, "kmh": 1 / 3.6,
        "mph": 0.44704,
        "kt": 0.514444, "kts": 0.514444, "knot": 0.514444, "knots": 0.514444,
        "ft/s": 0.3048, "fps": 0.3048,
    },
    "area": {
        "m^2": 1.0, "m2": 1.0, "sqm": 1.0,
        "cm^2": 1e-4, "cm2": 1e-4, "mm^2": 1e-6, "mm2": 1e-6,
        "in^2": 6.4516e-4, "in2": 6.4516e-4, "sqin": 6.4516e-4,
        "ft^2": 0.09290304, "ft2": 0.09290304, "sqft": 0.09290304,
    },
    "force": {
        "n": 1.0, "newton": 1.0, "newtons": 1.0,
        "kn": 1000.0,
        "kgf": 9.80665, "kg-f": 9.80665,
        "gf": 0.00980665, "g-f": 0.00980665,
        "lbf": 4.4482216,
    },
    "torque": {
        "nm": 1.0, "n-m": 1.0, "n.m": 1.0,
        "ncm": 0.01, "n-cm": 0.01,
        "kgcm": 0.0980665, "kg-cm": 0.0980665, "kgfcm": 0.0980665,
        "ozin": 0.00706155, "oz-in": 0.00706155,
    },
    "power": {"w": 1.0, "watt": 1.0, "watts": 1.0, "kw": 1000.0, "hp": 745.6999},
    "energy": {"j": 1.0, "wh": 3600.0, "kwh": 3.6e6},
    "charge": {"ah": 1.0, "mah": 0.001, "amp-hour": 1.0, "amphour": 1.0},
    "angle": {"deg": 1.0, "degree": 1.0, "degrees": 1.0, "°": 1.0,
              "rad": 180.0 / math.pi, "radian": 180.0 / math.pi,
              "radians": 180.0 / math.pi},
    "time": {"s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
             "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0,
             "h": 3600.0, "hr": 3600.0, "hour": 3600.0, "hours": 3600.0},
    "dimensionless": {"": 1.0, "%": 0.01, "pct": 0.01, "percent": 0.01},
}

# The SI base unit each dimension is expressed in.
_BASE = {
    "length": "m", "mass": "kg", "speed": "m/s", "area": "m^2", "force": "N",
    "torque": "N.m", "power": "W", "energy": "J", "charge": "Ah",
    "angle": "deg", "time": "s", "dimensionless": "",
}

# Which dimension a caller-requested target unit belongs to.
_DIMENSION_OF = {}
for _dim, _table in _FACTORS.items():
    for _suffix in _table:
        _DIMENSION_OF.setdefault(_suffix, _dim)


class UnitError(ValueError):
    """Raised when a value cannot be parsed or the unit is inappropriate."""


_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_VALUE_RE = re.compile(rf"^\s*({_NUMBER})\s*(.*?)\s*$")
_PROP_RE = re.compile(rf"^\s*({_NUMBER})\s*[xX*]\s*({_NUMBER})\s*(.*?)\s*$")


def _normalise_suffix(text: str) -> str:
    return text.strip().lower().replace("·", ".").replace(" ", "")


def parse(text, target_unit="", default=None):
    """Parse a user-entered quantity into SI (or into ``target_unit``'s dimension).

    ``target_unit`` names the unit a bare number is assumed to be in -- normally
    the SI base unit for that dimension. A blank or unparsable input returns
    ``default``; pass ``default=None`` and check for ``None`` to detect "missing".
    """
    if text is None:
        return default
    if isinstance(text, (int, float)):
        return float(text)

    raw = str(text).strip()
    if not raw:
        return default

    dimension = _DIMENSION_OF.get(_normalise_suffix(target_unit), "dimensionless")

    # "10x4.7" style propeller sizes: take the diameter, in inches by default.
    prop = _PROP_RE.match(raw)
    if prop and dimension == "length":
        suffix = _normalise_suffix(prop.group(3)) or "in"
        factor = _FACTORS["length"].get(suffix)
        if factor is None:
            raise UnitError(f"Unknown length unit '{prop.group(3)}' in '{raw}'.")
        return float(prop.group(1)) * factor

    match = _VALUE_RE.match(raw)
    if not match:
        raise UnitError(f"Could not read a number from '{raw}'.")

    value = float(match.group(1))
    suffix = _normalise_suffix(match.group(2))
    if not suffix:
        return value  # bare number keeps the target unit's meaning

    table = _FACTORS.get(dimension, {})
    if suffix in table:
        return value * table[suffix]

    # The suffix may be valid but for a different dimension -- say so clearly
    # rather than silently ignoring it.
    other = _DIMENSION_OF.get(suffix)
    if other:
        raise UnitError(
            f"'{match.group(2)}' is a {other} unit but a {dimension} value is "
            f"expected here (e.g. {_BASE.get(dimension, 'SI')}).")
    raise UnitError(f"Unknown unit '{match.group(2)}' in '{raw}'.")


def required(inputs, key, target_unit="", label=None):
    """Parse an input that must be present and non-zero-length."""
    value = parse(inputs.get(key), target_unit, None)
    if value is None:
        raise UnitError(f"{label or key} is required.")
    return value


def optional(inputs, key, target_unit="", default=0.0):
    """Parse an input, falling back to ``default`` when blank."""
    value = parse(inputs.get(key), target_unit, None)
    return default if value is None else value


def positive(inputs, key, target_unit="", label=None, default=None):
    """Parse an input that must be strictly greater than zero."""
    name = label or key
    value = parse(inputs.get(key), target_unit, None)
    if value is None:
        if default is None:
            raise UnitError(f"{name} is required.")
        return default
    if value <= 0:
        raise UnitError(f"{name} must be greater than zero (got {value:g}).")
    return value


def fraction(inputs, key, default=None, label=None):
    """Parse a value given either as a fraction (0.8) or a percentage (80%, 80).

    Values above 1 are read as percentages, which is how efficiencies and
    discharge limits are usually written on a spec sheet.
    """
    raw = inputs.get(key)
    if raw is None or not str(raw).strip():
        if default is None:
            raise UnitError(f"{label or key} is required.")
        return default
    text = str(raw).strip()
    is_percent = text.endswith("%")
    value = parse(text.rstrip("%"), "", None)
    if value is None:
        raise UnitError(f"Could not read {label or key}.")
    if is_percent or value > 1.0:
        value /= 100.0
    return value


# --------------------------------------------------------------- conversions
def to(value_si: float, unit: str) -> float:
    """Convert an SI value into ``unit``."""
    suffix = _normalise_suffix(unit)
    dimension = _DIMENSION_OF.get(suffix)
    if dimension is None:
        raise UnitError(f"Unknown unit '{unit}'.")
    return value_si / _FACTORS[dimension][suffix]


def dual(value_si: float, si_unit: str, imperial_unit: str, decimals=2) -> str:
    """Format a value in SI with the common imperial equivalent alongside."""
    imperial = to(value_si, imperial_unit)
    return f"{value_si:,.{decimals}f} {si_unit} ({imperial:,.{decimals}f} {imperial_unit})"


# Convenience wrappers used throughout the tool suite.
def m_to_in(v): return v / 0.0254
def in_to_m(v): return v * 0.0254
def kg_to_lb(v): return v / 0.45359237
def kg_to_oz(v): return v / 0.028349523
def ms_to_mph(v): return v / 0.44704
def ms_to_kmh(v): return v * 3.6
def ms_to_kt(v): return v / 0.514444
def nm_to_kgcm(v): return v / 0.0980665
def nm_to_ozin(v): return v / 0.00706155
def nm2_to_ozft2(v): return v / 2.992522  # wing loading, N/m^2 -> oz/ft^2
