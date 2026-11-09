"""Aerodynamic heating to Mach 2: recovery temperature, skin temperature, materials.

At Mach 2 the skin approaches the adiabatic-wall (recovery) temperature; the
stagnation temperature bounds noses and leading edges. Radiation removes only a
few kelvin at these speeds, but is included. Heat transfer uses Eckert's
reference-temperature method with the Reynolds analogy, and a lumped
thin-skin model gives the soak time, which decides whether a short dash heats
the structure at all.
"""

import math

from . import atmosphere, compressible

STEFAN_BOLTZMANN = 5.670374e-8
PRANDTL = 0.71
CP_AIR = 1004.0

# Indicative maximum service temperatures, K. Composite limits sit below the
# resin's (wet) glass transition; check your material data sheet.
MATERIALS = {
    "PLA (3D printed)": 323.0,
    "ABS / PETG (3D printed)": 348.0,
    "Glass/epoxy, room-temperature cure": 333.0,
    "Carbon/epoxy, room-temperature cure": 333.0,
    "Carbon/epoxy, 120 C cure": 366.0,
    "Carbon/epoxy, 180 C cure": 394.0,
    "Carbon/BMI": 450.0,
    "Carbon/polyimide": 560.0,
    "Aluminium 2024-T3 / 7075-T6": 394.0,
    "Aluminium 2618 (Concorde alloy)": 423.0,
    "Titanium Ti-6Al-4V": 673.0,
    "Steel 4130": 673.0,
}


def recovery_factor(turbulent=True):
    return PRANDTL ** (1 / 3) if turbulent else PRANDTL ** 0.5


def reference_temperature(static_temperature, mach, wall_temperature):
    """Eckert's reference temperature."""
    return static_temperature * (1.0 + 0.032 * mach ** 2
                                 + 0.58 * (wall_temperature / static_temperature - 1.0))


def heat_transfer_coefficient(mach, altitude, distance, wall_temperature, turbulent=True):
    """Local convective coefficient h (W/m^2/K) at ``distance`` from the leading edge."""
    if distance <= 0:
        raise ValueError("Distance from the leading edge must be positive.")
    air = atmosphere.at(altitude)
    velocity = mach * air.sound_speed
    t_star = reference_temperature(air.temperature, mach, wall_temperature)
    rho_star = air.pressure / (atmosphere.R_AIR * t_star)
    mu_star = atmosphere.viscosity(t_star)
    re_star = rho_star * velocity * distance / mu_star
    cf = 0.0592 * re_star ** -0.2 if turbulent else 0.664 / math.sqrt(re_star)
    stanton = 0.5 * cf * PRANDTL ** (-2 / 3)
    return stanton * rho_star * velocity * CP_AIR


def skin_temperature(mach, altitude, distance=0.5, emissivity=0.85, turbulent=True):
    """Radiative-equilibrium skin temperature and the adiabatic limits, K."""
    air = atmosphere.at(altitude)
    t_aw = compressible.recovery_temperature(air.temperature, mach, recovery_factor(turbulent))
    t_stag = compressible.stagnation_temperature(air.temperature, mach)
    if mach <= 0:
        return {"equilibrium": air.temperature, "recovery": t_aw, "stagnation": t_stag, "h": 0.0}

    def balance(t_wall):
        h = heat_transfer_coefficient(mach, altitude, distance, t_wall, turbulent)
        return h * (t_aw - t_wall) - emissivity * STEFAN_BOLTZMANN * (t_wall ** 4 - air.temperature ** 4)

    lo, hi = air.temperature, t_aw
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if balance(mid) > 0:
            lo = mid
        else:
            hi = mid
    t_wall = 0.5 * (lo + hi)
    return {"equilibrium": t_wall, "recovery": t_aw, "stagnation": t_stag,
            "h": heat_transfer_coefficient(mach, altitude, distance, t_wall, turbulent)}


def soak_time(h, skin_thickness, density, specific_heat, fraction=0.9):
    """Time for a thin, insulated-back skin to cover ``fraction`` of its temperature rise."""
    if min(h, skin_thickness, density, specific_heat) <= 0:
        raise ValueError("Soak-time inputs must be positive.")
    tau = density * specific_heat * skin_thickness / h
    return -tau * math.log(1.0 - fraction)
