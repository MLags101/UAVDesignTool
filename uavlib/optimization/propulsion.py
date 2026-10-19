"""Bounded measured propeller maps and DC-equivalent electric drive equations.

Motor constants must share the same terminal/current convention. A KV label alone
is insufficient: resistance, no-load current and ratings are mandatory. A BLDC
phase resistance cannot be substituted for equivalent terminal resistance.
"""
import bisect
import math
from .physics import interpolate


def motor_operating_point(shaft_power, rpm, motor, controller):
    """Equivalent terminal circuit at a known shaft load and speed."""
    if shaft_power < 0 or rpm <= 0:
        raise ValueError("Motor load must be nonnegative at positive RPM")
    for key in ("kv_rpm_per_volt", "max_current", "max_power", "max_rpm"):
        if not math.isfinite(motor[key]) or motor[key] <= 0:
            raise ValueError(f"Invalid motor {key}")
    if motor["resistance"] < 0 or motor["no_load_current"] < 0:
        raise ValueError("Motor resistance and no-load current must be nonnegative")
    eta = controller["efficiency"]
    if not 0 < eta <= 1 or controller["max_motor_current"] <= 0:
        raise ValueError("Controller needs efficiency and motor-side current limit")
    torque = shaft_power / (rpm * math.pi / 30)
    kt = 60 / (2 * math.pi * motor["kv_rpm_per_volt"])
    current = torque / kt + motor["no_load_current"]
    voltage = rpm / motor["kv_rpm_per_volt"] + current * motor["resistance"]
    return dict(rpm=rpm, shaft_power=shaft_power, torque=torque,
                motor_current=current, motor_voltage=voltage, bus_power=voltage * current / eta,
                motor_current_margin=(motor["max_current"] - current) / motor["max_current"],
                controller_current_margin=(controller["max_motor_current"] - current) / controller["max_motor_current"],
                motor_power_margin=(motor["max_power"] - shaft_power) / motor["max_power"],
                motor_rpm_margin=(motor["max_rpm"] - rpm) / motor["max_rpm"])


def propeller_point(propeller, rpm, speed, density):
    diameter = propeller["diameter"]
    maps = propeller["performance_map"]
    if min(diameter, rpm, density) <= 0 or speed < 0 or len(maps) < 2:
        raise ValueError("Propeller needs positive geometry/RPM/density and at least two RPM map slices")
    rpms = [row["rpm"] for row in maps]
    if any(not math.isfinite(x) or x <= 0 for x in rpms) or any(b <= a for a, b in zip(rpms, rpms[1:])):
        raise ValueError("Propeller map RPM slices must be positive and strictly increasing")
    if not rpms[0] <= rpm <= rpms[-1]:
        raise ValueError("Propeller RPM outside supplied map")
    j = speed / (rpm / 60 * diameter)
    i = min(max(bisect.bisect_right(rpms, rpm) - 1, 0), len(rpms) - 2)
    fraction = (rpm - rpms[i]) / (rpms[i + 1] - rpms[i])
    values = []
    for index, weight in ((i, 1 - fraction), (i + 1, fraction)):
        if weight == 0:
            continue
        points = maps[index]["points"]
        ct = interpolate([[p[0], p[1]] for p in points], j)
        cp = interpolate([[p[0], p[2]] for p in points], j)
        values.append((weight * ct, weight * cp))
    ct, cp = (sum(v[k] for v in values) for k in (0, 1))
    if ct <= 0 or cp <= 0 or j * ct > cp * (1 + 1e-6):
        raise ValueError("Map point outside positive-thrust powered-propeller domain")
    n = rpm / 60
    thrust = ct * density * n ** 2 * diameter ** 4
    power = cp * density * n ** 3 * diameter ** 5
    return dict(rpm=rpm, advance_ratio=j, thrust=thrust, shaft_power=power,
                torque=power / (2 * math.pi * n), propeller_efficiency=j * ct / cp)


def electric_drive(thrust, speed, density, propeller, motor, controller):
    """Find RPM producing requested thrust, then motor current/terminal voltage.

    Returns required DC-bus power before battery sag. The mission model solves
    that sag with all simultaneous loads and checks the required motor voltage.
    No RPM, map, voltage or current input is clipped to make hardware feasible.
    """
    import numpy as np
    from scipy.optimize import brentq
    if thrust <= 0:
        raise ValueError("Electric drive requires positive thrust")
    for key in ("kv_rpm_per_volt", "max_current", "max_power", "max_rpm"):
        if not math.isfinite(motor[key]) or motor[key] <= 0:
            raise ValueError(f"Invalid motor {key}")
    if motor["resistance"] < 0 or motor["no_load_current"] < 0:
        raise ValueError("Motor resistance and no-load current must be nonnegative")
    eta = controller["efficiency"]
    if not 0 < eta <= 1 or controller["max_motor_current"] <= 0:
        raise ValueError("Controller needs efficiency and motor-side current limit")
    maps = propeller["performance_map"]
    # Search each measured RPM interval and its common advance-ratio domain.
    # Gaps remain gaps; a root must never bridge an invalid operating region.
    roots = []
    for lower, upper in zip(maps, maps[1:]):
        lo, hi = lower["rpm"], min(upper["rpm"], motor["max_rpm"])
        jmin = max(lower["points"][0][0], upper["points"][0][0])
        jmax = min(lower["points"][-1][0], upper["points"][-1][0])
        if speed > 0:
            lo = max(lo, 60 * speed / (propeller["diameter"] * jmax)) if jmax > 0 else hi + 1
            if jmin > 0:
                hi = min(hi, 60 * speed / (propeller["diameter"] * jmin))
        elif jmin > 0:
            continue
        if hi < lo:
            continue
        grid = np.linspace(lo, hi, 33)
        previous = None
        for rpm in grid:
            try:
                error = propeller_point(propeller, float(rpm), speed, density)["thrust"] - thrust
            except ValueError:
                previous = None
                continue
            if abs(error) <= 1e-10 * max(1., thrust):
                roots.append(float(rpm))
            elif previous and error * previous[1] < 0:
                roots.append(brentq(lambda x: propeller_point(propeller, x, speed, density)["thrust"] - thrust,
                                    previous[0], float(rpm), xtol=1e-8))
            previous = (float(rpm), error)
    if not roots:
        raise ValueError("Requested thrust cannot be resolved inside the supplied propeller RPM/advance-ratio map")
    # Multiple positive-thrust roots are possible; retain the lowest bus-power
    # solution and expose ratings as margins rather than hiding an overload.
    answers = []
    for rpm in roots:
        point = propeller_point(propeller, rpm, speed, density)
        point.update(motor_operating_point(point["shaft_power"], rpm, motor, controller))
        answers.append(point)
    return min(answers, key=lambda answer: answer["bus_power"])
