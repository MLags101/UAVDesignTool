"""Beam bending and section properties for spars, booms and multirotor arms."""

import math

# Representative properties of materials used in model airframes.
# E is Young's modulus (Pa), sigma_allow a working stress with a margin already
# applied (Pa), and rho density (kg/m^3).
MATERIALS = {
    "Carbon fibre tube (pultruded)": {"E": 70e9,  "sigma": 600e6, "rho": 1600.0},
    "Carbon fibre tube (woven)":     {"E": 55e9,  "sigma": 450e6, "rho": 1550.0},
    "Aluminium 6061-T6":             {"E": 68.9e9, "sigma": 240e6, "rho": 2700.0},
    "Spruce":                        {"E": 11e9,  "sigma": 60e6,  "rho": 450.0},
    "Balsa (light)":                 {"E": 3.2e9, "sigma": 15e6,  "rho": 160.0},
    "Birch plywood":                 {"E": 10e9,  "sigma": 55e6,  "rho": 680.0},
    "Glass fibre":                   {"E": 25e9,  "sigma": 250e6, "rho": 1900.0},
    "PLA (printed)":                 {"E": 3.5e9, "sigma": 25e6,  "rho": 1240.0},
    "Nylon/CF (printed)":            {"E": 6.0e9, "sigma": 70e6,  "rho": 1200.0},
}


# --------------------------------------------------------- section properties
def tube_properties(outer_diameter: float, wall: float) -> dict:
    """Second moment of area and section modulus of a round tube.

    A tube is the efficient section for a spar because material far from the
    neutral axis carries the bending; halving the wall costs far less stiffness
    than halving the diameter.
    """
    if outer_diameter <= 0 or wall <= 0:
        raise ValueError("Diameter and wall thickness must be greater than zero.")
    inner_diameter = max(0.0, outer_diameter - 2.0 * wall)
    i = math.pi * (outer_diameter ** 4 - inner_diameter ** 4) / 64.0
    area = math.pi * (outer_diameter ** 2 - inner_diameter ** 2) / 4.0
    return {"I": i, "section_modulus": i / (outer_diameter / 2.0), "area": area,
            "inner_diameter": inner_diameter}


def solid_rod_properties(diameter: float) -> dict:
    i = math.pi * diameter ** 4 / 64.0
    return {"I": i, "section_modulus": i / (diameter / 2.0),
            "area": math.pi * diameter ** 2 / 4.0, "inner_diameter": 0.0}


def rectangular_properties(width: float, height: float) -> dict:
    """Rectangular spar cap or sheet, bending about the horizontal axis."""
    i = width * height ** 3 / 12.0
    return {"I": i, "section_modulus": i / (height / 2.0),
            "area": width * height, "inner_diameter": 0.0}


def spar_cap_properties(cap_width: float, cap_thickness: float,
                        separation: float) -> dict:
    """Two caps separated by a shear web -- the usual built-up model wing spar.

    Almost all the stiffness comes from the caps working at the separation
    distance, so this is modelled as two areas about the neutral axis.
    """
    area_one = cap_width * cap_thickness
    i = 2.0 * (cap_width * cap_thickness ** 3 / 12.0
               + area_one * (separation / 2.0) ** 2)
    height = separation + cap_thickness
    return {"I": i, "section_modulus": i / (height / 2.0),
            "area": 2.0 * area_one, "inner_diameter": 0.0}


# ------------------------------------------------------------------- loading
def bending_stress(moment: float, section_modulus: float) -> float:
    """sigma = M / Z, Pa."""
    if section_modulus <= 0:
        raise ValueError("Section modulus must be greater than zero.")
    return moment / section_modulus


def cantilever_tip_load(force: float, length: float) -> dict:
    """Root moment and tip deflection factors for a point load at the tip.

    This is how a multirotor arm is loaded: motor thrust at the far end.
    """
    return {"root_moment": force * length, "deflection_coefficient": 1.0 / 3.0}


def cantilever_deflection(force: float, length: float, modulus: float,
                          second_moment: float) -> float:
    """Tip deflection of a cantilever under a tip point load, m. PL^3/(3EI)."""
    if modulus <= 0 or second_moment <= 0:
        raise ValueError("Modulus and second moment must be greater than zero.")
    return force * length ** 3 / (3.0 * modulus * second_moment)


def elliptical_lift_root_moment(lift: float, span: float) -> float:
    """Root bending moment of one wing half under an elliptical lift distribution.

    The centroid of an elliptical half-span load sits at 4/(3*pi) of the
    semi-span, which is why this is noticeably lower than a uniform load.
    """
    half_span = span / 2.0
    half_lift = lift / 2.0
    return half_lift * (4.0 / (3.0 * math.pi)) * half_span


def uniform_lift_root_moment(lift: float, span: float) -> float:
    """Root bending moment with a rectangular (uniform) lift distribution.

    Conservative relative to elliptical -- the load centroid is at mid-semi-span.
    """
    half_span = span / 2.0
    half_lift = lift / 2.0
    return half_lift * half_span / 2.0


def wing_shear_at_root(lift: float) -> float:
    """Shear carried by one wing half at the root, N."""
    return lift / 2.0


def required_section_modulus(moment: float, allowable_stress: float,
                             safety_factor: float = 1.5) -> float:
    """Section modulus needed to carry a moment, m^3."""
    if allowable_stress <= 0:
        raise ValueError("Allowable stress must be greater than zero.")
    return moment * safety_factor / allowable_stress


def margin_of_safety(applied_stress: float, allowable_stress: float) -> float:
    """Margin of safety. Zero means exactly at the limit; negative fails."""
    if applied_stress <= 0:
        return float("inf")
    return allowable_stress / applied_stress - 1.0


def buckling_critical_load(modulus: float, second_moment: float, length: float,
                           end_condition: float = 1.0) -> float:
    """Euler critical buckling load, N.

    ``end_condition`` is the effective-length factor K: 1.0 pinned-pinned,
    0.5 fixed-fixed, 2.0 fixed-free (a cantilever arm).
    """
    if length <= 0:
        raise ValueError("Length must be greater than zero.")
    return (math.pi ** 2 * modulus * second_moment) / ((end_condition * length) ** 2)


def natural_frequency_cantilever(modulus: float, second_moment: float,
                                 length: float, mass_per_length: float,
                                 tip_mass: float = 0.0) -> float:
    """First bending mode of a cantilever, Hz.

    Motor and prop vibration lands in the 50-300 Hz band; an arm whose first
    mode sits in that range will resonate and blur the camera.
    """
    if length <= 0 or mass_per_length <= 0:
        raise ValueError("Length and mass per length must be greater than zero.")
    # Rayleigh approximation with an effective mass at the tip.
    effective_mass = 0.24 * mass_per_length * length + tip_mass
    stiffness = 3.0 * modulus * second_moment / length ** 3
    return math.sqrt(stiffness / effective_mass) / (2.0 * math.pi)


def deflection_note(deflection: float, length: float) -> str:
    """Judge a tip deflection against its span."""
    if length <= 0:
        return ""
    ratio = deflection / length
    if ratio > 0.10:
        return (f"Excessive: {ratio * 100:.1f}% of length. The structure is far "
                "too flexible and will affect handling.")
    if ratio > 0.05:
        return f"High: {ratio * 100:.1f}% of length. Acceptable only for gliders."
    if ratio > 0.02:
        return f"Moderate: {ratio * 100:.1f}% of length. Normal for a model wing."
    return f"Stiff: {ratio * 100:.1f}% of length."
