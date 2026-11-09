"""Mass build-up and fuel volume for small supersonic jet UAVs.

Statistical weight equations for jet aircraft (Raymer, Roskam) are fitted to
manned aircraft from about 5 t upward and extrapolate badly to a 50-1000 kg
UAV. This build-up is physical instead: skins and shells by areal mass, the
wing spar sized for bending and stiffness at the design load factor, the
engine from its thrust-to-weight ratio, plus fixed items. Areal masses are
technology assumptions to calibrate against your own construction.
"""

import math
from dataclasses import dataclass

from . import structures
from .atmosphere import G


@dataclass
class Technology:
    skin_areal_mass: float = 2.2         # kg/m^2 of wetted wing/tail skin
    body_areal_mass: float = 3.5         # kg/m^2 of fuselage wetted area, frames included
    spar_density: float = 1600.0         # kg/m^3, carbon spar caps
    allowable_stress: float = 400e6      # Pa
    modulus: float = 110e9               # Pa
    deflection_fraction: float = 0.06    # tip deflection limit / semi-span
    engine_thrust_to_weight: float = 10.0
    afterburner_mass_factor: float = 1.35
    installation_fraction: float = 0.25  # inlet duct, nozzle, mounts / engine mass
    fuel_system_fraction: float = 0.10   # tanks, pumps, lines / fuel capacity
    fixed_mass: float = 4.0              # avionics, actuators, wiring, kg
    recovery_fraction: float = 0.05      # parachute or gear / takeoff mass
    fuel_density: float = 800.0          # kg/m^3, kerosene
    wing_fuel_fraction: float = 0.30     # usable fraction of wing internal volume
    body_fuel_fraction: float = 0.35     # usable fraction of fuselage internal volume


def wing_volume(configuration):
    """Internal volume of the exposed biconvex wing, m^3."""
    g = configuration.wing_geometry
    r = 0.5 * configuration.body_diameter
    strips, total = 40, 0.0
    dy = (g["semi"] - r) / strips
    for i in range(strips):
        y = r + (i + 0.5) * dy
        chord = g["root"] * (1 - (1 - g["taper"]) * y / g["semi"])
        total += 2 * (2.0 / 3.0) * configuration.thickness_ratio * chord ** 2 * dy
    return total


def body_volume(configuration):
    n = 200
    dx = configuration.body_length / n
    return sum(math.pi * configuration.body_radius((i + 0.5) * dx) ** 2 * dx for i in range(n))


def fuel_volume_available(configuration, technology):
    return (technology.wing_fuel_fraction * wing_volume(configuration)
            + technology.body_fuel_fraction * body_volume(configuration))


def build_up(configuration, technology, takeoff_mass, sls_thrust, afterburner, payload,
             fuel_capacity, load_factor=6.0, structure_margin=1.0):
    """Component masses (kg) for an assumed takeoff mass."""
    surfaces, _ = configuration.wetted_areas()
    g = configuration.wing_geometry
    root_depth = configuration.thickness_ratio * g["root"]
    lift = load_factor * takeoff_mass * G * structure_margin
    caps = structures.required_spar_cap_area(lift, configuration.span, root_depth,
                                             technology.allowable_stress, technology.modulus,
                                             technology.deflection_fraction)
    cap_area = max(caps["stress"], caps["deflection"])
    # Two caps, tapering with the chord: about 2/3 of the root area on average.
    spar = 2 * cap_area * configuration.span * technology.spar_density * (2 / 3)
    engine = sls_thrust / (G * technology.engine_thrust_to_weight)
    if afterburner:
        engine *= technology.afterburner_mass_factor
    breakdown = {
        "wing": surfaces["wing"] * technology.skin_areal_mass * structure_margin + spar,
        "fuselage": surfaces["fuselage"] * technology.body_areal_mass * structure_margin,
        "tails": (surfaces["horizontal tail"] + surfaces["vertical tail"]) * technology.skin_areal_mass,
        "engine": engine,
        "installation": engine * technology.installation_fraction,
        "fuel system": fuel_capacity * technology.fuel_system_fraction,
        "fixed equipment": technology.fixed_mass,
        "recovery": technology.recovery_fraction * takeoff_mass,
        "payload": payload,
        "fuel": fuel_capacity,
    }
    return breakdown, {"spar_cap_area": cap_area, "spar_limited_by":
                       "stress" if caps["stress"] >= caps["deflection"] else "stiffness"}


def close(configuration, technology, sls_thrust, afterburner, payload, fuel_capacity,
          load_factor=6.0, structure_margin=1.0, guess=None, tolerance=1e-6):
    """Fixed-point mass closure; returns (takeoff mass, breakdown, notes)."""
    mass = guess or max(10.0, 3.0 * (payload + fuel_capacity))
    for _ in range(200):
        breakdown, notes = build_up(configuration, technology, mass, sls_thrust, afterburner,
                                    payload, fuel_capacity, load_factor, structure_margin)
        new = sum(breakdown.values())
        if not math.isfinite(new) or new > 1e6:
            raise ValueError("Mass closure diverged; the structure fraction exceeds one.")
        if abs(new - mass) < tolerance * max(1.0, new):
            return new, breakdown, notes
        mass = new
    raise ValueError("Mass closure did not converge.")
