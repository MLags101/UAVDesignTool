"""International Standard Atmosphere.

Replaces the three copy-pasted ``get_density()`` implementations that used to
live in WingSizing, FlightEstimator and ControlSurfaceEstimator. Those were
troposphere-only and provided density alone; this covers the stratosphere as
well and adds the viscosity and speed of sound that Reynolds and Mach
calculations need.
"""

import math
from dataclasses import dataclass

RHO_0 = 1.225        # sea level density, kg/m^3
T_0 = 288.15         # sea level temperature, K
P_0 = 101325.0       # sea level pressure, Pa
LAPSE = 0.0065       # troposphere lapse rate, K/m
R_AIR = 287.05287    # specific gas constant, J/(kg*K)
GAMMA = 1.4          # ratio of specific heats
G = 9.80665          # standard gravity, m/s^2

TROPOPAUSE = 11000.0  # m
T_TROPOPAUSE = T_0 - LAPSE * TROPOPAUSE            # 216.65 K
P_TROPOPAUSE = P_0 * (T_TROPOPAUSE / T_0) ** (G / (R_AIR * LAPSE))

# Sutherland's law constants for air.
MU_REF = 1.716e-5    # Pa*s at T_REF
T_REF = 273.15       # K
S_SUTHERLAND = 110.4  # K


@dataclass(frozen=True)
class Atmosphere:
    """Air properties at one altitude."""
    altitude: float      # m
    temperature: float   # K
    pressure: float      # Pa
    density: float       # kg/m^3
    viscosity: float     # Pa*s (dynamic)
    sound_speed: float   # m/s

    @property
    def kinematic_viscosity(self) -> float:
        """Kinematic viscosity, m^2/s."""
        return self.viscosity / self.density

    @property
    def density_ratio(self) -> float:
        """Density relative to sea level -- the sigma used in performance work."""
        return self.density / RHO_0

    def summary(self) -> str:
        return (f"Altitude {self.altitude:,.0f} m: "
                f"rho {self.density:.4f} kg/m^3, "
                f"T {self.temperature - 273.15:.1f} degC, "
                f"a {self.sound_speed:.1f} m/s")


def viscosity(temperature_k: float) -> float:
    """Dynamic viscosity of air by Sutherland's law, Pa*s."""
    t = max(temperature_k, 1.0)
    return MU_REF * (t / T_REF) ** 1.5 * (T_REF + S_SUTHERLAND) / (t + S_SUTHERLAND)


def at(altitude_m: float) -> Atmosphere:
    """Air properties at a geopotential altitude, valid to 20 km."""
    h = max(0.0, float(altitude_m))

    if h <= TROPOPAUSE:
        temperature = T_0 - LAPSE * h
        pressure = P_0 * (temperature / T_0) ** (G / (R_AIR * LAPSE))
    else:
        # Isothermal layer from 11 km to 20 km.
        temperature = T_TROPOPAUSE
        pressure = P_TROPOPAUSE * math.exp(-G * (h - TROPOPAUSE)
                                           / (R_AIR * T_TROPOPAUSE))

    density = pressure / (R_AIR * temperature)
    return Atmosphere(
        altitude=h,
        temperature=temperature,
        pressure=pressure,
        density=density,
        viscosity=viscosity(temperature),
        sound_speed=math.sqrt(GAMMA * R_AIR * temperature),
    )


def density(altitude_m: float) -> float:
    """Air density at altitude, kg/m^3. Drop-in for the old ``get_density``."""
    return at(altitude_m).density


def density_from_conditions(pressure_pa: float, temperature_c: float,
                            relative_humidity: float = 0.0) -> float:
    """Density from measured field conditions.

    Humid air is *less* dense than dry air at the same pressure, which matters
    on a hot, humid flying day. ``relative_humidity`` is 0-1.
    """
    t_k = temperature_c + 273.15
    if relative_humidity <= 0:
        return pressure_pa / (R_AIR * t_k)

    # Saturation vapour pressure, Tetens' formula (Pa).
    p_sat = 610.78 * math.exp(17.27 * temperature_c / (temperature_c + 237.3))
    p_vapour = min(relative_humidity, 1.0) * p_sat
    p_dry = pressure_pa - p_vapour
    return (p_dry / (R_AIR * t_k)) + (p_vapour / (461.495 * t_k))


def density_altitude(density_kg_m3: float) -> float:
    """The ISA altitude at which air has the given density, m.

    A hot day at a 1500 m field can fly like 3000 m; this is what actually
    drives hover margin and takeoff distance.
    """
    ratio = density_kg_m3 / RHO_0
    if ratio <= 0:
        return float("inf")
    # Invert rho/rho0 = (T/T0)^(g/(R*L) - 1) within the troposphere.
    exponent = G / (R_AIR * LAPSE) - 1.0
    temperature = T_0 * ratio ** (1.0 / exponent)
    return (T_0 - temperature) / LAPSE


def reynolds(velocity_ms: float, length_m: float, altitude_m: float = 0.0) -> float:
    """Reynolds number for a chord at altitude."""
    air = at(altitude_m)
    return air.density * velocity_ms * length_m / air.viscosity


def mach(velocity_ms: float, altitude_m: float = 0.0) -> float:
    return velocity_ms / at(altitude_m).sound_speed


# Reynolds bands that matter for model aircraft. Below ~70k most airfoils
# suffer a laminar separation bubble and Cd rises steeply, which is why
# thin, cambered, low-Re-specific sections are used on small models.
RE_BANDS = (
    (70_000, "Very low Re. Laminar separation bubbles dominate; use a section "
              "designed for low Re (e.g. SD7037, AG series, E387). Expect poor "
              "performance from thick or fully turbulent sections."),
    (200_000, "Low Re. Typical of small RC models. Airfoil choice matters a "
              "great deal here; consult polars at this exact Re."),
    (500_000, "Moderate Re. Most sport and trainer RC models operate here. "
              "Standard sections behave close to their published polars."),
    (float("inf"), "High Re. Boundary layer is largely turbulent; full-scale "
                   "airfoil data is broadly applicable."),
)


def reynolds_note(re: float) -> str:
    """Plain-language guidance for a Reynolds number."""
    for threshold, note in RE_BANDS:
        if re < threshold:
            return note
    return RE_BANDS[-1][1]
