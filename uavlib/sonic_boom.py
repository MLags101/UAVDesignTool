"""Far-field sonic boom: Whitham F-function and the N-wave at the ground.

The aircraft is represented by its equivalent area A_e(x): the Mach 1
cross-sectional area plus the lift contribution beta L(x) / (rho V^2), where
L(x) is the lift accumulated to station x. Whitham's F-function

    F(y) = 1/(2 pi) int_0^y A_e''(xi) / sqrt(y - xi) dxi

ages into an N-wave whose ground overpressure and duration are

    dp = K_r sqrt(p_v p_g) 2^(1/4) gamma beta^(1/4) sqrt(I) h^(-3/4) / sqrt(gamma + 1)
    dt = 2^(5/4) sqrt(gamma + 1) M sqrt(I) h^(1/4) / (a_v beta^(3/4))

with I the largest running integral of F. This is the theory behind Carlson's
simplified method (NASA TP-1122): steady level flight, standard atmosphere
handled through the geometric-mean pressure, no winds and no ray-tube
amplification factor. Treat it as a conceptual estimate. A Concorde-like
geometry at Mach 2 and 16.5 km gives about 104 Pa against the ~93 Pa measured.
"""

import math

from . import atmosphere
from .area_rule import pchip_derivative, pchip_slopes

GAMMA = 1.4


def lift_equivalent_area(xs, planform_cumulative, weight, mach, altitude, load_factor=1.0):
    """Equivalent area from lift, with lift spread in proportion to planform area."""
    air = atmosphere.at(altitude)
    beta = math.sqrt(mach ** 2 - 1.0)
    rho_v2 = air.density * (mach * air.sound_speed) ** 2
    total = planform_cumulative[-1]
    if total <= 0:
        raise ValueError("Planform area distribution is empty.")
    lift = load_factor * weight
    return [beta * lift * c / total / rho_v2 for c in planform_cumulative]


def f_function(xs, areas, ys):
    """Whitham F-function at offsets ``ys`` from the nose (exact for cubic A_e)."""
    slopes = pchip_slopes(xs, areas)
    n = len(xs) * 2
    x0, x1 = xs[0], xs[-1]
    grid = [x0 + (x1 - x0) * i / n for i in range(n + 1)]
    derivative = [pchip_derivative(xs, areas, slopes, x) for x in grid]
    out = []
    for y in ys:
        y_abs = x0 + y
        total = derivative[0] / math.sqrt(y) if y > 0 else 0.0
        for a, b, d0, d1 in zip(grid, grid[1:], derivative, derivative[1:]):
            if a >= y_abs:
                break
            curvature = (d1 - d0) / (b - a)
            total += curvature * 2.0 * (math.sqrt(y_abs - a) - math.sqrt(max(y_abs - b, 0.0)))
        out.append(total / (2.0 * math.pi))
    return out


def ground_signature(xs, areas, mach, altitude, reflection=1.9, points=160):
    """N-wave ground overpressure (Pa) and duration (s) for an equivalent area."""
    if not 1.0 < mach:
        raise ValueError("A sonic boom needs supersonic flight.")
    vehicle = atmosphere.at(altitude)
    ground = atmosphere.at(0.0)
    cutoff = ground.sound_speed / vehicle.sound_speed
    length = xs[-1] - xs[0]
    ys = [length * 1.2 * (i + 1) / points for i in range(points)]
    f = f_function(xs, areas, ys)
    running, best, total, previous = [], 0.0, 0.0, (0.0, 0.0)
    for y, value in zip(ys, f):
        total += 0.5 * (value + previous[1]) * (y - previous[0])
        previous = (y, value)
        running.append(total)
        best = max(best, total)
    beta = math.sqrt(mach ** 2 - 1.0)
    result = {"f_y": ys, "f": f, "integral": best, "cutoff_mach": cutoff,
              "reaches_ground": mach > cutoff}
    if mach <= cutoff or best <= 0:
        result.update(overpressure=0.0, duration=0.0)
        return result
    h = altitude
    result["overpressure"] = (reflection * math.sqrt(vehicle.pressure * ground.pressure)
                              * 2 ** 0.25 * GAMMA * beta ** 0.25 * math.sqrt(best) * h ** -0.75
                              / math.sqrt(GAMMA + 1))
    result["duration"] = (2 ** 1.25 * math.sqrt(GAMMA + 1) * mach * math.sqrt(best) * h ** 0.25
                          / (vehicle.sound_speed * beta ** 0.75))
    return result


def aircraft_boom(configuration, weight, mach, altitude, reflection=1.9):
    """Ground boom for a :class:`uavlib.supersonic.Configuration` in level flight."""
    xs, volume = configuration.area_distribution()
    wing = configuration.wing_geometry
    r = 0.5 * configuration.body_diameter
    cumulative = []
    for x in xs:
        # Planform area of the exposed wing ahead of station x, by strips.
        strips, semi, area = 20, wing["semi"], 0.0
        dy = (semi - r) / strips
        for i in range(strips):
            y = r + (i + 0.5) * dy
            chord = wing["root"] * (1 - (1 - wing["taper"]) * y / semi)
            x_le = wing["x_le_root"] + y * wing["tan_le"]
            area += 2 * min(max(x - x_le, 0.0), chord) * dy
        cumulative.append(area)
    lift_area = lift_equivalent_area(xs, cumulative, weight, mach, altitude)
    equivalent = [v + l for v, l in zip(volume, lift_area)]
    signature = ground_signature(xs, equivalent, mach, altitude, reflection)
    signature["equivalent_area"] = (xs, equivalent)
    return signature
