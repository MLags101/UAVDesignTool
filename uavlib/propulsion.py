"""Rotor and propeller models.

Momentum theory for hover, blade-element-informed empirical models for
propellers, and the electric drive chain from battery to shaft.
"""

import math

from . import atmosphere as atm
from .atmosphere import G

# Figure of merit: how close a real rotor gets to the momentum-theory ideal.
# Small multirotor props are far from ideal because of low Reynolds number and
# a blunt hub; large, well-designed rotors do much better.
FM_TYPICAL = {
    "hobby": 0.55,        # sub-10 inch, cheap injection-moulded
    "quality": 0.65,      # good carbon multirotor prop, 10-18 inch
    "large": 0.75,        # 20 inch and up, well matched
    "helicopter": 0.80,   # full-scale-like rotor
}

# Loss when two rotors run coaxially (over-under / X8 / Y6). The lower rotor
# works in the wash of the upper one and both suffer.
COAXIAL_EFFICIENCY = 0.80


def disk_area(diameter: float) -> float:
    """Rotor disk area, m^2."""
    return math.pi * (diameter / 2.0) ** 2


def disk_loading(thrust: float, diameter: float, count: int = 1) -> float:
    """Thrust per unit disk area, N/m^2.

    The single strongest predictor of hover efficiency: low disk loading means
    a large, slow-moving column of air, which costs less power.
    """
    area = disk_area(diameter) * max(1, count)
    if area <= 0:
        raise ValueError("Rotor diameter must be greater than zero.")
    return thrust / area


def induced_velocity(thrust: float, diameter: float, altitude: float = 0.0,
                     count: int = 1) -> float:
    """Induced velocity through the disk in hover, m/s."""
    rho = atm.density(altitude)
    area = disk_area(diameter) * max(1, count)
    if area <= 0 or thrust <= 0:
        return 0.0
    return math.sqrt(thrust / (2.0 * rho * area))


def ideal_hover_power(thrust: float, diameter: float, altitude: float = 0.0,
                      count: int = 1) -> float:
    """Momentum-theory induced power for hover, W.

    P_ideal = T^1.5 / sqrt(2 * rho * A). This is the floor; no rotor beats it.
    """
    rho = atm.density(altitude)
    area = disk_area(diameter) * max(1, count)
    if area <= 0 or thrust <= 0:
        return 0.0
    return thrust ** 1.5 / math.sqrt(2.0 * rho * area)


def hover_power(thrust: float, diameter: float, figure_of_merit: float = 0.65,
                altitude: float = 0.0, count: int = 1) -> float:
    """Real shaft power required to hover, W.

    This is the calculation that lets a hover estimate start from the aircraft's
    mass rather than from a power figure the designer would have to already know.
    """
    fm = max(0.05, min(figure_of_merit, 1.0))
    return ideal_hover_power(thrust, diameter, altitude, count) / fm


def thrust_from_power(power: float, diameter: float, figure_of_merit: float = 0.65,
                      altitude: float = 0.0, count: int = 1) -> float:
    """Invert the hover power relation to get thrust from available power, N."""
    rho = atm.density(altitude)
    area = disk_area(diameter) * max(1, count)
    fm = max(0.05, min(figure_of_merit, 1.0))
    if area <= 0 or power <= 0:
        return 0.0
    return (power * fm * math.sqrt(2.0 * rho * area)) ** (2.0 / 3.0)


def hover_efficiency(thrust: float, power: float) -> float:
    """Hover efficiency in grams of thrust per watt -- the figure hobbyists quote."""
    if power <= 0:
        return 0.0
    return (thrust / G * 1000.0) / power


def forward_flight_power(mass: float, velocity: float, diameter: float,
                         count: int, flat_plate_area: float,
                         figure_of_merit: float = 0.65,
                         altitude: float = 0.0) -> dict:
    """Total power for a multirotor in level forward flight, W.

    Three contributions: induced power (falls with speed as the rotor gains an
    inflow), parasite power from the airframe (rises as V^3), and a profile
    term. The sum has a minimum, which is the best cruise speed.
    """
    rho = atm.density(altitude)
    weight = mass * G
    area = disk_area(diameter) * max(1, count)

    # Induced velocity in forward flight: solve v^2 = vh^2 / sqrt(V^2 + v^2)
    # iteratively (Glauert's high-speed approximation converges quickly).
    vh = math.sqrt(weight / (2.0 * rho * area)) if area > 0 else 0.0
    v_i = vh
    for _ in range(60):
        denominator = math.sqrt(velocity ** 2 + v_i ** 2)
        v_new = vh ** 2 / denominator if denominator > 1e-9 else vh
        if abs(v_new - v_i) < 1e-9:
            v_i = v_new
            break
        v_i = 0.5 * (v_i + v_new)  # damped update for stability

    induced = weight * v_i
    parasite = 0.5 * rho * velocity ** 3 * flat_plate_area
    # Profile power is roughly constant in hover and grows mildly with speed.
    profile = (ideal_hover_power(weight, diameter, altitude, count)
               * (1.0 / max(0.05, figure_of_merit) - 1.0)
               * (1.0 + 3.0 * (velocity / max(vh, 1e-6)) ** 2 / 100.0))

    total = induced + parasite + profile
    return {"induced": induced, "parasite": parasite, "profile": profile,
            "total": total, "induced_velocity": v_i}


def best_cruise_speed(mass: float, diameter: float, count: int,
                      flat_plate_area: float, figure_of_merit: float = 0.65,
                      altitude: float = 0.0, v_max: float = 40.0) -> tuple:
    """Speed of minimum power (best endurance) and of best range, m/s.

    Best range is where power/velocity is minimised -- the tangent from the
    origin to the power curve -- and is always faster than best endurance.
    """
    best_v, best_p = 0.0, float("inf")
    best_range_v, best_ratio = 0.0, float("inf")

    steps = int(v_max * 10)
    for i in range(1, steps + 1):
        v = i / 10.0
        p = forward_flight_power(mass, v, diameter, count, flat_plate_area,
                                 figure_of_merit, altitude)["total"]
        if p < best_p:
            best_p, best_v = p, v
        ratio = p / v
        if ratio < best_ratio:
            best_ratio, best_range_v = ratio, v

    return best_v, best_range_v


# ------------------------------------------------------------- propellers
def pitch_speed(rpm: float, pitch_m: float) -> float:
    """Theoretical speed at which the prop stops producing thrust, m/s.

    The airframe's cruise speed should sit well below this -- typically 60-80%
    of pitch speed -- or the prop is unloaded and thrust collapses.
    """
    return rpm * pitch_m / 60.0


def static_coefficients(pitch_diameter_ratio: float) -> tuple:
    """Static thrust and power coefficients (Ct, Cp) from pitch/diameter.

    Linear fits to published APC-style data for the slow-flyer and multirotor
    props used on models. For a 10x4.7 (p/D = 0.47) these give Ct = 0.108 and
    Cp = 0.043, matching manufacturer data to within a few percent.

    Accurate to roughly +/-20%. Where the manufacturer publishes Ct and Cp, use
    those instead via :func:`static_thrust_from_ct`.
    """
    pd = max(0.2, min(float(pitch_diameter_ratio), 1.2))
    ct = 0.070 + 0.080 * pd
    cp = 0.008 + 0.075 * pd
    return ct, cp


def static_thrust_from_ct(ct: float, rpm: float, diameter: float,
                          altitude: float = 0.0) -> float:
    """Thrust from a known thrust coefficient, N. T = Ct * rho * n^2 * D^4."""
    n = rpm / 60.0
    return ct * atm.density(altitude) * n ** 2 * diameter ** 4


def static_thrust(diameter_m: float, pitch_m: float, rpm: float,
                  altitude: float = 0.0) -> float:
    """Static (zero airspeed) thrust from prop geometry and RPM, N."""
    if diameter_m <= 0 or rpm <= 0:
        return 0.0
    ct, _ = static_coefficients(pitch_m / diameter_m)
    return static_thrust_from_ct(ct, rpm, diameter_m, altitude)


def static_shaft_power(diameter_m: float, pitch_m: float, rpm: float,
                       altitude: float = 0.0) -> float:
    """Shaft power absorbed by the prop at static thrust, W.

    P = Cp * rho * n^3 * D^5. This is what sizes the motor.
    """
    if diameter_m <= 0 or rpm <= 0:
        return 0.0
    _, cp = static_coefficients(pitch_m / diameter_m)
    n = rpm / 60.0
    return cp * atm.density(altitude) * n ** 3 * diameter_m ** 5


def prop_thrust_coefficient(thrust: float, rpm: float, diameter: float,
                            altitude: float = 0.0) -> float:
    """Non-dimensional thrust coefficient Ct = T / (rho * n^2 * D^4)."""
    n = rpm / 60.0
    rho = atm.density(altitude)
    denominator = rho * n ** 2 * diameter ** 4
    return thrust / denominator if denominator > 0 else 0.0


def prop_power_coefficient(power: float, rpm: float, diameter: float,
                           altitude: float = 0.0) -> float:
    """Non-dimensional power coefficient Cp = P / (rho * n^3 * D^5)."""
    n = rpm / 60.0
    rho = atm.density(altitude)
    denominator = rho * n ** 3 * diameter ** 5
    return power / denominator if denominator > 0 else 0.0


def advance_ratio(velocity: float, rpm: float, diameter: float) -> float:
    """J = V / (n * D)."""
    n = rpm / 60.0
    return velocity / (n * diameter) if n > 0 and diameter > 0 else 0.0


def propeller_efficiency(advance: float, ct: float, cp: float) -> float:
    """eta = J * Ct / Cp."""
    return advance * ct / cp if cp > 0 else 0.0


# ----------------------------------------------------------- electric drive
def motor_rpm(kv: float, voltage: float, load_factor: float = 0.85) -> float:
    """Loaded motor RPM.

    Kv is the unloaded constant; under a propeller load a motor turns roughly
    80-90% of Kv*V.
    """
    return kv * voltage * max(0.1, min(load_factor, 1.0))


def drive_chain_efficiency(propeller: float = 0.70, motor: float = 0.80,
                           esc: float = 0.95, wiring: float = 0.98) -> float:
    """Overall electrical-to-propulsive efficiency.

    Multiplying the stages matters: 0.7 prop alone flatters the result badly
    when the motor and ESC together cost another 25%.
    """
    return propeller * motor * esc * wiring


def electrical_power(shaft_power: float, motor: float = 0.80,
                     esc: float = 0.95, wiring: float = 0.98) -> float:
    """Electrical power drawn for a required shaft power, W."""
    chain = motor * esc * wiring
    if chain <= 0:
        raise ValueError("Efficiencies must be greater than zero.")
    return shaft_power / chain


def figure_of_merit_note(fm: float) -> str:
    if fm < 0.45:
        return "Poor. Check that the prop suits the disk loading and RPM."
    if fm < 0.60:
        return "Typical of small hobby propellers."
    if fm < 0.72:
        return "Good. Representative of quality carbon multirotor props."
    if fm <= 0.82:
        return "Excellent. Achievable only with large, well-matched rotors."
    return "Optimistic. Values above 0.82 are rare outside full-scale rotorcraft."
